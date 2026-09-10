//
//  JStackHostBar.swift
//  The host's menu bar app — the whole thing, in one file.
//
//  The host is a terminal program on purpose: installed by a script you can
//  read, run by a user LaunchAgent, answering on a port with no window and no
//  Dock tile. That is the trust argument — a program that watches your terminal
//  sessions should be one you can audit before you run it — but it leaves the
//  machine with no way to answer "is it up, and what is it doing" short of
//  curling a port. This is that answer, in the one place a background program
//  is allowed to be seen.
//
//  It belongs to the host and not to any client app. A status item lives and
//  dies with the process that created it, so putting one in a client means the
//  indicator disappears the moment you quit the client — while the host it was
//  indicating is still running. This app runs under its own LaunchAgent beside
//  the host's, which is the only arrangement where the icon means what it says.
//
//  One file, compiled on your machine by `install.sh`. Nothing is downloaded,
//  so there is no signature to trust and no notarization to check: the binary
//  in your menu bar was built from the source next to it, by you.
//
//  Unsandboxed — a locally built app, not a Store one — so it may do the thing
//  a sandboxed app cannot: operate the LaunchAgent. Start, stop and restart are
//  real here. That is why this is the host's UI and not the client's.
//

import AppKit
import CoreImage
import Foundation
import Network

// MARK: - Where the host is

/// Everything about the installed host, read off the LaunchAgent that installed
/// it rather than guessed.
///
/// The plist is the one record of what the host was *installed to be*. A host
/// installed with `--state-dir` keeps its token somewhere this app would never
/// find by resolving defaults, and reading defaults instead would report on a
/// different, empty host — the same trap `jstack-host` avoids by adopting the
/// installed environment before every read command.
enum HostAgent {
    /// The LaunchAgent that owns the host's lifecycle.
    ///
    /// `com.jremote.host` is what `jstack-host install` writes, and on a
    /// machine the installer set up that is the answer. It is not the only
    /// one: a host embedded in a larger application is started and stopped by
    /// *that* application's agent, and a menu hardcoded to this label decides
    /// there is nothing installed, hides Restart and Stop, and leaves the one
    /// machine whose hub you would actually want to operate with a menu that
    /// only reports. `JREMOTE_AGENT_LABEL` names the real one.
    ///
    /// Read from this process's own environment and never through
    /// `environment()` below — that resolves by *reading this label's plist*,
    /// so sourcing the label from it would be circular.
    static let label: String = {
        let env = ProcessInfo.processInfo.environment["JREMOTE_AGENT_LABEL"] ?? ""
        return env.isEmpty ? "com.jremote.host" : env
    }()
    static let defaultPort = 9090

    static var plistURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(label).plist")
    }

    static var isInstalled: Bool {
        FileManager.default.fileExists(atPath: plistURL.path)
    }

    private static func job() -> [String: Any]? {
        guard let data = try? Data(contentsOf: plistURL),
              let plist = try? PropertyListSerialization.propertyList(
                  from: data, options: [], format: nil) as? [String: Any]
        else { return nil }
        return plist
    }

    /// The port to look on: this app's own `--port` if it was given one,
    /// otherwise the port the installed agent serves on — taken from the argv
    /// launchd execs, which is the same string the host is running with.
    static func port() -> Int {
        let mine = ProcessInfo.processInfo.arguments
        if let i = mine.firstIndex(of: "--port"), i + 1 < mine.count,
           let p = Int(mine[i + 1]) { return p }
        guard let args = job()?["ProgramArguments"] as? [String],
              let i = args.firstIndex(of: "--port"),
              i + 1 < args.count,
              let p = Int(args[i + 1])
        else { return defaultPort }
        return p
    }

    /// The address the host was installed to bind, or nil where nothing on
    /// disk says.
    ///
    /// Nil is a real answer and not a default: an embedded host has no agent
    /// of its own to read, and guessing `0.0.0.0` there would put "reachable
    /// from your LAN" under a machine's name on the evidence of nothing.
    static func bind() -> String? {
        let mine = ProcessInfo.processInfo.arguments
        if let i = mine.firstIndex(of: "--bind"), i + 1 < mine.count {
            return mine[i + 1]
        }
        guard let args = job()?["ProgramArguments"] as? [String],
              let i = args.firstIndex(of: "--bind"), i + 1 < args.count
        else { return nil }
        return args[i + 1]
    }

    /// The state dir the host is using. From the agent when there is one;
    /// otherwise the package's own default — which is the right answer for a
    /// host started with `jstack-host serve`, a documented way to run one and
    /// a case with no plist to read anything off.
    static func stateDir() -> URL {
        if let state = environment()["JREMOTE_STATE_DIR"], !state.isEmpty {
            return URL(fileURLWithPath: (state as NSString).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".local/state/jremote")
    }

    /// The `JREMOTE_*` overrides the host runs under. `install_host` always
    /// pins `JREMOTE_STATE_DIR` in the plist, even when nobody passed
    /// `--state-dir`, so this is never empty for an installed host.
    ///
    /// An explicit export in this process's own environment wins over the
    /// plist — the same precedence `adopt_installed_environment` applies on the
    /// Python side, where the agent's settings go *beneath* whatever the caller
    /// set on purpose. Under launchd there is nothing exported, so the plist is
    /// what answers; run by hand against a second host, the export is.
    static func environment() -> [String: String] {
        var out: [String: String] = [:]
        if let env = job()?["EnvironmentVariables"] as? [String: Any] {
            for (k, v) in env where k.hasPrefix("JREMOTE_") {
                out[k] = String(describing: v)
            }
        }
        for (k, v) in ProcessInfo.processInfo.environment where k.hasPrefix("JREMOTE_") {
            out[k] = v
        }
        return out
    }

    /// The bearer token file, resolved the way the host resolves it:
    /// `JREMOTE_TOKEN_PATH` wins outright, otherwise `api-token` inside the
    /// state dir.
    static func tokenPath() -> URL {
        if let explicit = environment()["JREMOTE_TOKEN_PATH"], !explicit.isEmpty {
            return URL(fileURLWithPath: (explicit as NSString).expandingTildeInPath)
        }
        return stateDir().appendingPathComponent("api-token")
    }

    /// Read fresh every poll, never cached. A host provisioned after this app
    /// launched — the ordinary first-install order — would otherwise stay
    /// tokenless in the menu until someone thought to restart the menu bar.
    static func token() -> String? {
        guard let raw = try? String(contentsOf: tokenPath(), encoding: .utf8)
        else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    static func logDirectory() -> URL {
        stateDir().appendingPathComponent("logs")
    }

    /// The program launchd execs for the host. Its *directory* is the useful
    /// part: an embedded host runs out of some environment's `bin`, and the
    /// host's own tooling is installed into that same `bin`.
    static func programPath() -> String? {
        (job()?["ProgramArguments"] as? [String])?.first
    }
}

// MARK: - What the host says

struct Health: Decodable {
    var service: String?
    var profile: String?
    var provisioned: Bool?

    /// Is this *our* host, or merely something else holding the port?
    ///
    /// Worth asking: the port is a default, and another program answering it
    /// with JSON that happens to lack these keys would otherwise be reported as
    /// a healthy host. `service` is the marker the host stamps deliberately.
    var isOurHost: Bool { service == "jremote-host" }
}

/// One row of the Active section. Every field optional: this app renders a
/// menu, and a menu that fails to draw because the host grew a key is worse
/// than one that draws a row with a blank subtitle.
struct Session: Decodable {
    var sessionId: String?
    var agentName: String?
    var emoji: String?
    var subMode: String?
    var windowName: String?
    var live: Bool?
    var managed: Bool?
    var onMac: Bool?
    /// Alive — a process is holding this session — whether or not it is
    /// producing anything this second. `live` is the narrower claim.
    var running: Bool?

    /// What to call it, in the order the answer is most specific: the window's
    /// own title, then the agent it belongs to, then nothing anyone can act on.
    var title: String {
        let name = (agentName ?? "").trimmingCharacters(in: .whitespaces)
        let mode = (subMode ?? "").trimmingCharacters(in: .whitespaces)
        let window = (windowName ?? "").trimmingCharacters(in: .whitespaces)
        let who = mode.isEmpty ? name : "\(name) · \(mode)"
        if !who.trimmingCharacters(in: .init(charactersIn: " ·")).isEmpty { return who }
        if !window.isEmpty { return window }
        return sessionId ?? "session"
    }

    /// `live` is producing output right now; `onMac` is a window showing it.
    /// A session can be either without the other, and the dot says which.
    var mark: String {
        if live == true { return "●" }
        if onMac == true || managed == true { return "○" }
        return " "
    }
}

struct ActiveSessions: Decodable { var sessions: [Session]? }

/// `/host` — the route that proves which machine this is. Behind the token by
/// design, and that is the point: a host answering on loopback that rejects
/// our token is not our host, whatever it would have claimed.
struct HostIdentity: Decodable {
    var hostId: String?
    var name: String?
    var profile: String?
    var features: [String: Bool]?

    /// local / open / managed — the host's own verdict on how a device off
    /// this network reaches it, computed by `jstack_host.mode`. Nil where an
    /// older host predates the field; the headline falls back to the coarser
    /// hub/leaf read below rather than drawing nothing.
    var mode: HostMode?

    /// Hub or leaf, taken from the host's own answer rather than inferred.
    ///
    /// `tunnel_pairing` is true only where `wg0.conf` is — and that file *is*
    /// the mesh, the peer list the interface honours. A hub holds it; a leaf
    /// dialled out to one and has no peers of its own to mint. Nil where the
    /// host did not say, which is not the same as leaf and must not be drawn
    /// as one. Superseded by `mode` on a current host; kept for the fallback.
    var isHub: Bool? { features?["tunnel_pairing"] }
}

/// The `mode` block `/host` carries: the word, the one-line explanation, and
/// whether the mode is live right now (a managed host's tunnel can be down
/// while the attachment itself stands).
struct HostMode: Decodable {
    var mode: String?
    var note: String?
    var live: Bool?
}

/// One snapshot of the machine, as the menu will render it.
struct HostState {
    var installed = false
    var health: Health?
    var sessions: [Session] = []
    /// The token exists but the board refused it — worth its own state, because
    /// it is the one failure that looks identical to "nothing is running".
    var unauthorized = false
    /// Identified through `/host` rather than `/api/health`: this API is being
    /// served by something larger that owns the health route. Its lifecycle is
    /// not ours, so the agent controls stay off.
    var embedded = false

    var isUp: Bool { health?.isOurHost == true }
    var isProvisioned: Bool { health?.provisioned == true }
    var liveCount: Int { sessions.filter { $0.live == true }.count }

    /// Which machine on the mesh this is, and what it is doing about it.
    var identity: HostIdentity?
    /// The bind address the agent was installed with, where a plist says so.
    var bind: String?

    /// The machine row's second line: the port, and what this Mac is on the
    /// mesh.
    ///
    /// The port because it is the fact you actually need — the thing you type,
    /// the thing you forward, the thing that is wrong when nothing answers.
    /// "1 working" was a number already on the row above it.
    ///
    /// Hub or leaf is said outright because the two are reached in opposite
    /// directions and the menu is where that gets confused: a hub is dialled
    /// *into* and only from outside your LAN if something forwards or tunnels
    /// to it, while a leaf dialled *out* to its hub and needs nothing forwarded
    /// at all. Saying "hub" without saying it is not itself reachable from the
    /// internet would be the more useful half of the truth left out.
    var headline: String {
        guard isUp else {
            return installed ? "Not answering on port \(HostAgent.port())"
                             : "No hub on this Mac"
        }
        var parts = ["Port \(HostAgent.port())"]
        // Loopback is the one bind that changes what the port means, and it is
        // knowable only where an agent plist recorded it. Unknown says nothing
        // rather than claiming reach this app never measured.
        if let bind, bind == "127.0.0.1" || bind == "localhost" {
            parts.append("this Mac only")
        } else if let m = identity?.mode?.mode {
            // The host's own verdict — local / open / managed — in its own word.
            // A managed host whose tunnel is down still says "managed", and adds
            // that it is not reachable through its parent right now, because the
            // attachment stands while the path is out.
            parts.append(m)
            if identity?.mode?.live == false { parts.append("offline") }
        } else {
            // Older host with no mode field: the coarser hub/leaf read.
            switch identity?.isHub {
            case true:  parts.append("hub")
            case false: parts.append("leaf")
            case nil:   break
            }
        }
        if !isProvisioned { parts.append("no token") }
        // A host answering with no agent of its own and no larger app behind it
        // is `jstack-host serve` — a foreground run in somebody's terminal.
        // Worth a word, because it is the one arrangement that does not survive
        // closing that window.
        if !installed && !embedded { parts.append("in a terminal") }
        return parts.joined(separator: " · ")
    }

}

// MARK: - Asking

/// Polls the host and hands back a whole snapshot.
///
/// Two requests, and the second is the reason the token is read at all:
/// `/api/health` is deliberately unauthenticated so "is anyone there" can be
/// answered before a token exists, but it says nothing about what is on the
/// machine — the board is behind the token, and this app is the one client
/// entitled to read it off disk, because it is running on the host, as the user
/// who owns it.
final class HostProbe {
    private let session: URLSession

    init() {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 3
        config.waitsForConnectivity = false
        session = URLSession(configuration: config)
    }

    /// Where the token-bearing routes live. `/api/health` is not under it —
    /// the health probe is mounted on the app itself, precisely so it stays
    /// reachable without the version prefix or the token.
    private static let apiPrefix = "/api/jremote/v1"

    func poll(_ done: @escaping (HostState) -> Void) {
        var state = HostState()
        state.installed = HostAgent.isInstalled
        state.bind = HostAgent.bind()
        let port = HostAgent.port()
        let base = "http://127.0.0.1:\(port)"
        let finish = { DispatchQueue.main.async { done(state) } }

        get("\(base)/api/health", token: nil) { data, _ in
            if let data, let health = try? Self.decoder.decode(Health.self, from: data) {
                state.health = health
            }
            let token = HostAgent.token()

            let loadSessions = {
                guard let token else { return finish() }
                self.get("\(base)\(Self.apiPrefix)/sessions/active", token: token) { data, status in
                    if status == 401 || status == 403 { state.unauthorized = true }
                    if let data,
                       let active = try? Self.decoder.decode(ActiveSessions.self, from: data) {
                        state.sessions = active.sessions ?? []
                    }
                    finish()
                }
            }

            // `/host` on the healthy path too, not only the embedded one. It
            // carries hub-or-leaf, and a menu that can only say which of those
            // this Mac is when the host was awkward to find is a menu that
            // says it least often on the machines set up properly.
            if state.isUp {
                guard let token else { return loadSessions() }
                return self.get("\(base)\(Self.apiPrefix)/host", token: token) { data, _ in
                    if let data,
                       let identity = try? Self.decoder.decode(HostIdentity.self, from: data) {
                        state.identity = identity
                    }
                    loadSessions()
                }
            }

            // `/api/health` did not claim to be a host. That is not the same as
            // no host: the router is mountable inside a larger app, and such a
            // deployment answers `/api/health` with its own payload while
            // serving this whole API underneath. So ask the host's own identity
            // route, which is behind the token *because* the token is the proof
            // — a loopback host that rejects ours is not ours, whatever it
            // would have claimed. A 200 here settles it.
            guard let token else { return finish() }
            self.get("\(base)\(Self.apiPrefix)/host", token: token) { data, status in
                guard status == 200, let data,
                      let identity = try? Self.decoder.decode(HostIdentity.self, from: data)
                else { return finish() }
                state.health = Health(service: "jremote-host",
                                      profile: identity.profile,
                                      provisioned: true)
                state.embedded = true
                state.identity = identity
                loadSessions()
            }
        }
    }

    private static var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    /// Kill a session, through the host's own close route so the teardown is
    /// the one the app and the board already use — not a second implementation
    /// that gets the window or the registry wrong.
    ///
    /// `review=false`, and that is the whole difference between the two words.
    /// `review=true` is *Close*: EOF, `claude` exits cleanly, its SessionEnd
    /// hook fires and spawns a review of the session you just ended. Kill is
    /// not a polite exit — asking for one and getting a review agent is the
    /// opposite of what the word promises. False SIGKILLs the pane, no hook
    /// runs, nothing is spawned. The transcript is append-only and resume
    /// tolerates a truncated tail, so the work is still there.
    func kill(sid: String, token: String,
              _ done: @escaping (Bool, String) -> Void) {
        let port = HostAgent.port()
        guard let url = URL(string:
            "http://127.0.0.1:\(port)\(Self.apiPrefix)/sessions/\(sid)/close?review=false")
        else { return done(false, "could not build the request") }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        // The teardown waits on `claude` to exit, up to ten seconds — well past
        // the three the polls are configured for.
        req.timeoutInterval = 20
        session.dataTask(with: req) { data, response, error in
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            let detail: String
            if let error { detail = error.localizedDescription }
            else if let data, let text = String(data: data, encoding: .utf8), !text.isEmpty {
                detail = text
            } else { detail = "the hub answered \(status)" }
            DispatchQueue.main.async { done(status == 200, detail) }
        }.resume()
    }

    private func get(_ url: String, token: String?,
                     _ done: @escaping (Data?, Int) -> Void) {
        guard let url = URL(string: url) else { return done(nil, 0) }
        var req = URLRequest(url: url)
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        session.dataTask(with: req) { data, response, _ in
            done(data, (response as? HTTPURLResponse)?.statusCode ?? 0)
        }.resume()
    }
}

// MARK: - Doing

/// The operations the menu offers. Every one of them shells out to the same
/// tools a person would type — `launchctl` for the agent, `jstack-host` for the
/// host — because a second implementation of "restart the host" is a second
/// thing to keep true.
/// What this Mac *is*, for the row that names it.
///
/// "Hosting — jj · port 9090" described the software's configuration, which is
/// not what someone opening a menu about their machine is looking for. A hub
/// is a machine; the row should say which one, the way every other Apple
/// surface does — a Mac Studio icon and the words "M2 Max Mac Studio".
enum Machine {
    /// `system_profiler` is the only source that knows the marketing name, and
    /// it costs the better part of a second — so it is asked once, lazily, at
    /// the first menu build rather than on every poll.
    static let name: String = {
        let out = HostControl.run("/usr/sbin/system_profiler", ["SPHardwareDataType"]).out
        func field(_ label: String) -> String {
            for line in out.split(separator: "\n") {
                let parts = line.split(separator: ":", maxSplits: 1)
                guard parts.count == 2,
                      parts[0].trimmingCharacters(in: .whitespaces) == label
                else { continue }
                return parts[1].trimmingCharacters(in: .whitespaces)
            }
            return ""
        }
        let model = field("Model Name")                       // "Mac Studio"
        // "Apple M2 Max" — the word Apple is not information on an Apple menu.
        var chip = field("Chip")
        if chip.hasPrefix("Apple ") { chip.removeFirst("Apple ".count) }
        switch (model.isEmpty, chip.isEmpty) {
        case (false, false): return "\(chip) \(model)"        // "M2 Max Mac Studio"
        case (false, true):  return model
        case (true, false):  return chip
        case (true, true):   return Host.current().localizedName ?? "This Mac"
        }
    }()

    /// The device glyph. Named from the marketing name rather than the model
    /// identifier: `Mac14,13` says nothing without a table that goes stale
    /// every autumn, and "Mac Studio" is stable English.
    static let symbol: String = {
        let m = name.lowercased()
        if m.contains("macbook")    { return "laptopcomputer" }
        if m.contains("mac studio") { return "macstudio" }
        if m.contains("mac mini")   { return "macmini" }
        if m.contains("mac pro")    { return "macpro.gen3" }
        if m.contains("imac")       { return "desktopcomputer" }
        return "desktopcomputer"
    }()
}

/// The client app, if this Mac has one installed.
///
/// Found by bundle id rather than a path: an app is wherever the person who
/// installed it put it, and `/Applications` is a guess. `JREMOTE_APP_BUNDLE_ID`
/// names a different build — a debug one, say — without a rebuild of this.
enum RemoteApp {
    /// The bundle name, which is the product's name and nothing else.
    ///
    /// Not a bundle identifier: an identifier carries whoever signed the
    /// build — a person's or a company's name — and this file ships in a
    /// public repository, so hardcoding one would publish that. Set
    /// `JREMOTE_APP_BUNDLE_ID` to name your own build's identifier instead;
    /// it wins where it is set, and nothing is written down here.
    static let bundleName = "jRemote"

    /// Resolved on every read, not cached: the app can be installed while this
    /// menu bar item is running, and an item that stays missing until the next
    /// login is one that looks broken.
    static var url: URL? {
        if let id = ProcessInfo.processInfo.environment["JREMOTE_APP_BUNDLE_ID"],
           !id.isEmpty {
            return NSWorkspace.shared.urlForApplication(withBundleIdentifier: id)
        }
        let fm = FileManager.default
        for dir in [URL(fileURLWithPath: "/Applications"),
                    fm.homeDirectoryForCurrentUser.appendingPathComponent("Applications")] {
            let candidate = dir.appendingPathComponent("\(bundleName).app")
            if fm.fileExists(atPath: candidate.path) { return candidate }
        }
        return nil
    }
}

/// Tells a running client to bring its board forward rather than whatever
/// window happens to be frontmost.
///
/// `NSWorkspace.openApplication` activates and reuses the running instance,
/// but activation only raises whatever is already frontmost — a thread
/// window left on top stays on top. Which window is "the board" is knowable
/// only inside that process, so the client listens on this loopback port for
/// one line and does the choosing itself; see that file's own BoardControl
/// for the far end. Fixed on both ends, not negotiated: a runtime port needs
/// a second channel to publish it on, which is the exact problem this exists
/// to avoid, and one Mac runs one client.
///
/// Best-effort. No client, an older build with no listener, a cold launch
/// still short of `listen()` — every one of those is answered by the
/// activation call already made, so a failure here is silent.
enum BoardRaise {
    private static let port = NWEndpoint.Port(rawValue: 52845)!

    /// Retries through a cold launch: `openApplication` returns once the
    /// process exists, not once its listener is up, and the gap between the
    /// two is exactly the window this walks.
    static func send(deadline: TimeInterval = 5) {
        let start = Date()
        var done = false

        func attempt() {
            let connection = NWConnection(host: "127.0.0.1", port: port, using: .tcp)
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    connection.send(content: Data("RAISE-BOARD\n".utf8),
                                    completion: .contentProcessed { _ in
                        done = true
                        connection.cancel()
                    })
                case .failed, .waiting:
                    connection.cancel()
                    guard !done, Date().timeIntervalSince(start) < deadline else { return }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3, execute: attempt)
                default:
                    break
                }
            }
            connection.start(queue: .main)
        }
        attempt()
    }
}

/// The client app's mark, drawn rather than shipped.
///
/// A chevron and a cursor — a prompt, which is what the app opens onto. The
/// geometry is the app icon's own, reduced to what it actually is: two
/// round-capped strokes on SF Symbols' 70.459-unit cap-height canvas, so it
/// carries the same optical weight as the system glyphs on the rows around it
/// at every size and in both appearances.
///
/// Drawn in code because this app is one Swift file compiled by `install.sh`
/// with nothing but `swiftc`. A custom SF Symbol means an asset catalog, an
/// asset catalog means `actool`, and `actool` ships with Xcode rather than the
/// command line tools — a whole new build dependency for one icon. A PDF or a
/// PNG in the bundle would be a binary blob in a repository whose entire claim
/// is that you can read the thing you are about to run.
enum JRemoteGlyph {
    /// The canvas the geometry was authored on: SF Symbols' cap height, which
    /// is why scaling against the system font's cap height below lines this up
    /// with `NSImage(systemSymbolName:)` instead of near it.
    private static let capHeight: CGFloat = 70.459
    private static let width: CGFloat = 92.6406
    private static let stroke: CGFloat = 18.2672
    /// The left edge of the *drawn* result — the first stroke's centre less its
    /// own round cap, which is what actually reaches the edge of the box.
    private static let originX: CGFloat = 9.766

    /// Centre lines in the authoring space, where y runs negative upward from
    /// the baseline.
    private static let chevron = [
        CGPoint(x: 18.8996, y: -61.3254),
        CGPoint(x: 55.4339, y: -35.2295),
        CGPoint(x: 18.8996, y: -9.1336),
    ]
    private static let cursor = [
        CGPoint(x: 65.8722, y: -9.1336),
        CGPoint(x: 93.2730, y: -9.1336),
    ]

    static func image(size pointSize: CGFloat) -> NSImage {
        let scale = NSFont.systemFont(ofSize: pointSize).capHeight / capHeight
        let box = NSSize(width: width * scale, height: capHeight * scale)
        let image = NSImage(size: box, flipped: false) { _ in
            func map(_ p: CGPoint) -> NSPoint {
                NSPoint(x: (p.x - originX) * scale, y: -p.y * scale)
            }
            let path = NSBezierPath()
            path.move(to: map(chevron[0]))
            for point in chevron.dropFirst() { path.line(to: map(point)) }
            path.move(to: map(cursor[0]))
            path.line(to: map(cursor[1]))
            path.lineWidth = stroke * scale
            path.lineCapStyle = .round
            path.lineJoinStyle = .round
            NSColor.black.setStroke()
            path.stroke()
            return true
        }
        // A template, so it inverts with the menu the way every other row's
        // glyph does — a mark that stays black on a highlighted row is the one
        // that reads as pasted on.
        image.isTemplate = true
        return image
    }
}

/// What `jstack-host pair --json` answers with — the parts the pairing dialog
/// draws, instead of the paragraph it used to echo. `link` is the same
/// `jremote://pair` URL the installer fires at a local app; here it goes into
/// a QR so a *remote* device's camera can be the thing that fires it.
struct MintedPairing {
    let name: String
    let code: String
    let expiresIn: Int
    let firstAddress: String?
    let link: String?

    init?(json: String) {
        guard let data = json.data(using: .utf8),
              let raw = try? JSONSerialization.jsonObject(with: data),
              let top = raw as? [String: Any],
              let code = top["code"] as? String, !code.isEmpty
        else { return nil }
        self.code = code
        name = (top["name"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "a device"
        expiresIn = top["expires_in"] as? Int ?? 600
        let addresses = top["addresses"] as? [[String: Any]] ?? []
        firstAddress = addresses.first?["url"] as? String
        link = top["link"] as? String
    }

    /// "10 minutes", from seconds — the dialog says how long the code lives,
    /// and a number nobody rounds for them is homework.
    var validFor: String {
        let mins = max(1, expiresIn / 60)
        return mins == 1 ? "1 minute" : "\(mins) minutes"
    }
}

enum HostControl {
    /// `gui/<uid>`: the per-user domain, which is where a LaunchAgent lives and
    /// the reason none of this needs a password.
    static var domain: String { "gui/\(getuid())" }

    @discardableResult
    static func run(_ launchPath: String, _ args: [String]) -> (out: String, code: Int32) {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: launchPath)
        task.arguments = args
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = pipe
        do { try task.run() } catch { return ("", -1) }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        return (String(data: data, encoding: .utf8) ?? "", task.terminationStatus)
    }

    static func restart() {
        run("/bin/launchctl", ["kickstart", "-k", "\(domain)/\(HostAgent.label)"])
    }

    static func stop() {
        run("/bin/launchctl", ["bootout", "\(domain)/\(HostAgent.label)"])
    }

    static func start() {
        run("/bin/launchctl", ["bootstrap", domain, HostAgent.plistURL.path])
        run("/bin/launchctl", ["kickstart", "-k", "\(domain)/\(HostAgent.label)"])
    }

    /// Where `jstack-host` is. The installer passes `--host-bin` on the command
    /// line because it is the one thing that knows for certain; the search is
    /// the fallback for an app launched by hand.
    static var hostBinary: String? = {
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: "--host-bin"), i + 1 < args.count,
           FileManager.default.isExecutableFile(atPath: args[i + 1]) {
            return args[i + 1]
        }
        // Beside the host's own interpreter, before any fixed location.
        //
        // An embedded host runs out of the environment the larger application
        // was installed into, and `jstack-host` is installed into that same
        // environment — so the agent's own argv names the copy that belongs to
        // the host actually running here. The fixed paths below can only find
        // whichever copy a machine happens to have on it, which on a machine
        // with two is a coin toss, and on this one is nothing at all: the
        // binary is in the dashboard's virtualenv and none of them look there.
        // That is why Pair a Device quietly failed to appear.
        if let program = HostAgent.programPath() {
            let sibling = URL(fileURLWithPath: program)
                .deletingLastPathComponent()
                .appendingPathComponent("jstack-host").path
            if FileManager.default.isExecutableFile(atPath: sibling) { return sibling }
        }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        for candidate in ["\(home)/.local/bin/jstack-host",
                          "/opt/homebrew/bin/jstack-host",
                          "/usr/local/bin/jstack-host"] {
            if FileManager.default.isExecutableFile(atPath: candidate) { return candidate }
        }
        return nil
    }()
}

/// Whether a LaunchAgent brings itself up at login, and flipping that.
///
/// There is no permission to grant here and no API to ask. A *user* LaunchAgent
/// in `~/Library/LaunchAgents` is loaded at login by launchd with no prompt and
/// no sudo — it shows up afterwards in Login Items & Extensions as a switch you
/// may turn off, not as one you had to turn on. So the setting is a property of
/// the plist, and this reads and writes exactly that.
enum LoginAgent {
    static func plistURL(_ label: String) -> URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(label).plist")
    }

    static func exists(_ label: String) -> Bool {
        FileManager.default.fileExists(atPath: plistURL(label).path)
    }

    private static func job(_ label: String) -> [String: Any]? {
        guard let data = try? Data(contentsOf: plistURL(label)),
              let plist = try? PropertyListSerialization.propertyList(
                  from: data, options: [], format: nil) as? [String: Any]
        else { return nil }
        return plist
    }

    /// Does it come up at login?
    ///
    /// `RunAtLoad` is the obvious half. The other half is `KeepAlive` as a bare
    /// `true`, which means "keep this running" with no condition attached — so
    /// launchd starts it the moment the job is loaded, whatever `RunAtLoad`
    /// says or fails to say. A *dictionary* `KeepAlive` is conditional
    /// (`SuccessfulExit` and friends) and starts nothing on its own.
    ///
    /// Getting this wrong is how a checkbox ends up unticked next to a hub that
    /// has come up at every login for months.
    static func startsAtLogin(_ label: String) -> Bool {
        guard let job = job(label) else { return false }
        if job["KeepAlive"] as? Bool == true { return true }
        return job["RunAtLoad"] as? Bool == true
    }

    /// True where `KeepAlive` alone guarantees the start. Then `RunAtLoad` is
    /// not the knob, and a switch offering to flip it is a switch that lies —
    /// so the row is shown ticked and locked, with the reason on the tooltip,
    /// rather than offered as a choice that would not take.
    static func pinnedOn(_ label: String) -> Bool {
        job(label)?["KeepAlive"] as? Bool == true
    }

    /// Write the flag. Nothing is unloaded and nothing is restarted: launchd
    /// reads these files fresh at the next login, which is the only moment this
    /// setting means anything — and booting the job out to make a next-login
    /// setting "take" would stop the very thing being configured.
    @discardableResult
    static func setStartsAtLogin(_ label: String, _ on: Bool) -> Bool {
        guard var job = job(label) else { return false }
        job["RunAtLoad"] = on
        guard let data = try? PropertyListSerialization.data(
                  fromPropertyList: job, format: .xml, options: 0),
              (try? data.write(to: plistURL(label), options: .atomic)) != nil
        else { return false }
        return true
    }
}

/// This app's own LaunchAgent label — its bundle identifier, which is what
/// `install.sh` writes into both the bundle and the plist. Read rather than
/// repeated, so the two cannot drift apart.
enum MenuBarAgent {
    static let label = Bundle.main.bundleIdentifier ?? "com.jremote.menubar"
}

// MARK: - The menu bar

final class StatusController: NSObject {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let probe = HostProbe()
    private var timer: Timer?
    private var state = HostState()

    override init() {
        super.init()
        item.button?.image = Self.glyph("desktopcomputer")
        item.button?.imagePosition = .imageLeading
        item.menu = NSMenu()
        item.menu?.delegate = self
        refresh()
        // Ten seconds: the answer changes without this app doing anything — an
        // install finishes in a terminal, the agent is booted out, the machine
        // wakes with it not back yet. An indicator frozen on the answer it got
        // at launch is the failure this exists to avoid.
        let t = Timer(timeInterval: 10, repeats: true) { [weak self] _ in self?.refresh() }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    private static func glyph(_ name: String) -> NSImage? {
        let image = NSImage(systemSymbolName: name, accessibilityDescription: "JStack host")
        image?.isTemplate = true
        return image
    }

    func refresh() {
        probe.poll { [weak self] state in
            guard let self else { return }
            self.state = state
            self.draw()
            if self.item.menu?.highlightedItem == nil { self.build() }
        }
    }

    /// One shape, badged rather than swapped: an icon that changes silhouette
    /// between states is one nobody learns to find, and finding it is the whole
    /// job of a menu bar item. Down is the same glyph dimmed, which is what
    /// `appearsDisabled` is for.
    private func draw() {
        guard let button = item.button else { return }
        let unprovisioned = state.isUp && !state.isProvisioned
        // `server.rack`: what this machine is doing, not what it is. A desktop
        // glyph in a menu bar reads as "a Mac" — which is every Mac — where a
        // rack reads as the thing serving, which is the one fact the icon has
        // room to carry.
        button.image = Self.glyph("server.rack")
        // Colour rather than a second silhouette, so the shape stays learnable:
        // the badged variants exist only for some symbols, and swapping to one
        // moves the icon's outline the moment something is wrong — exactly when
        // you want to find it in the same place.
        button.contentTintColor = unprovisioned ? .systemOrange : nil
        button.appearsDisabled = !state.isUp
        // The count is the running indicator: a number that appears when work
        // is actually in flight, and no chrome at all when the machine is idle.
        let live = state.liveCount
        button.title = live > 0 ? " \(live)" : ""
        // The same line the menu's first row shows, since it is the answer to
        // "what is this icon telling me" and the icon has no room for it.
        button.toolTip = "\(Machine.name) — \(state.headline)"
    }

    private func build() {
        let menu = NSMenu()
        menu.autoenablesItems = false

        // ── The machine, and what it is running ─────────────────────────────
        //
        // Two rows that open, rather than two lists spilled onto one surface.
        // The top level is then short enough to read at a glance — which is
        // what a menu bar is for — and each row's contents are one hover away
        // instead of scrolled past on the way to the next thing.
        //
        // No "This Mac" heading above them: the machine's own name is the row,
        // and a heading that says less than the line under it is furniture.

        let machine = NSMenuItem(title: Machine.name, action: nil, keyEquivalent: "")
        machine.image = Self.glyph(Machine.symbol, size: 26)
        machine.attributedTitle = Self.twoLine(Machine.name, state.headline)
        // No tooltip. The row already says the two things there are to say, on
        // two lines, without being hovered — a bubble that fades in over them a
        // second later can only repeat it or contradict it.
        machine.submenu = controlsMenu()
        menu.addItem(machine)

        menu.addItem(processesItem())

        // ── The app ─────────────────────────────────────────────────────────
        menu.addItem(.separator())
        if RemoteApp.url != nil {
            let remote = Self.action("jRemote", #selector(doOpenApp), self)
            remote.image = JRemoteGlyph.image(size: 13)
            menu.addItem(remote)
        }
        if FileManager.default.fileExists(atPath: HostAgent.logDirectory().path) {
            menu.addItem(Self.action("Open Log Folder", #selector(doLogs), self,
                                     symbol: "folder"))
        }
        // No Refresh. `menuWillOpen` re-polls, so everything below the pointer
        // was fetched on the way to it — a button that re-fetches data a
        // fraction of a second old is a button that can only ever appear to do
        // nothing, and teaches that the numbers need convincing to be true.

        // No Quit by default. This is the hub's indicator, and the hub runs
        // whether or not anyone is looking at it — so "quit" here never meant
        // "stop the hub", it meant "hide the icon", which is not a thing worth
        // a permanent slot in a menu about the hub. Set JREMOTE_MENUBAR_QUIT=1
        // to put it back; `menubar/install.sh --uninstall` removes it for good.
        //
        // An environment variable and not a checkbox: a setting whose whole
        // effect is whether a menu item exists is a menu item about the menu,
        // and it would sit in the same list as the ones about the hub.
        if ProcessInfo.processInfo.environment["JREMOTE_MENUBAR_QUIT"] == "1" {
            menu.addItem(.separator())
            let quit = Self.action("Quit Menu Bar", #selector(doQuit), self)
            quit.toolTip = "Takes this icon off until the next login. "
                + "The host keeps running."
            menu.addItem(quit)
        }

        menu.delegate = self
        item.menu = menu
    }

    /// The Active section. Rows are informational — a menu bar is where you
    /// look to find out, and the thing you would do about it is a terminal
    /// command or the app, neither of which belongs behind a status item.
    /// What opens off the machine's row: the things you can do to the hub.
    ///
    /// Start / Stop only when there is an agent to operate. A hub running in a
    /// terminal is stopped by the terminal it is running in, and a Shut Down
    /// that boots out a job which does not exist is a button that lies.
    private func controlsMenu() -> NSMenu {
        let sub = NSMenu()
        sub.autoenablesItems = false
        if state.installed {
            if state.isUp {
                sub.addItem(Self.action("Restart Hub", #selector(doRestart), self,
                                        symbol: "arrow.clockwise"))
                sub.addItem(Self.action("Shut Down Hub", #selector(doStop), self,
                                        symbol: "power"))
            } else {
                sub.addItem(Self.action("Start Hub", #selector(doStart), self,
                                        symbol: "power"))
            }
        }
        if state.isUp, HostControl.hostBinary != nil {
            sub.addItem(Self.action("Pair a Device…", #selector(doPair), self,
                                    symbol: "plus.circle"))
        }
        if sub.items.isEmpty {
            sub.addItem(Self.caption("No agent to operate this hub."))
        }

        // ── Login ───────────────────────────────────────────────────────────
        //
        // Here and not behind a Settings row of its own. Whether the hub comes
        // up at login is a fact about this machine's hub, which is what this
        // submenu already is — a Settings item next to it would be a second
        // door onto the same room.
        sub.addItem(.separator())
        if HostAgent.isInstalled {
            let hub = Self.check("Start Hub at Login",
                                 on: LoginAgent.startsAtLogin(HostAgent.label),
                                 #selector(doToggleHubLogin), self)
            if LoginAgent.pinnedOn(HostAgent.label) {
                hub.action = nil
                hub.isEnabled = false
                hub.toolTip = "Always on: this agent is set to be kept running, "
                    + "so launchd starts it at login whatever this says. "
                    + "Change it where the agent is installed from."
            } else {
                hub.toolTip = "Nothing to grant — a user LaunchAgent loads at "
                    + "login on its own. Takes effect at the next login."
            }
            sub.addItem(hub)
        }
        if LoginAgent.exists(MenuBarAgent.label) {
            let bar = Self.check("Start Menu Bar at Login",
                                 on: LoginAgent.startsAtLogin(MenuBarAgent.label),
                                 #selector(doToggleBarLogin), self)
            bar.toolTip = "Off means the icon is gone until you launch the app "
                + "again. The hub is unaffected either way."
            sub.addItem(bar)
        }

        // No agent label, state dir or token path on the menu. They are the
        // answer to "why is this menu wrong", which is a question asked while
        // something is broken and never while it works — and a permanent row
        // that cannot be clicked reads as a control that died, not as a fact.
        // Copy Diagnostics carries all three, untruncated, to the place they
        // are actually usable.
        sub.addItem(.separator())
        let copy = Self.action("Copy Diagnostics", #selector(doCopyDiagnostics), self,
                               symbol: "doc.on.clipboard")
        copy.toolTip = "Everything on this submenu, plus what the host answered, "
            + "as text. No token value is copied."
        sub.addItem(copy)

        return sub
    }

    /// A checkbox row. `.on`/`.off` rather than a tick drawn into the title, so
    /// it reads as a setting to the system and to VoiceOver both.
    private static func check(_ title: String, on: Bool,
                              _ selector: Selector,
                              _ target: AnyObject) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: selector, keyEquivalent: "")
        item.target = target
        item.isEnabled = true
        item.state = on ? .on : .off
        return item
    }

    /// The processes row: a count you read at the top level, a list you open.
    private func processesItem() -> NSMenuItem {
        let sub = NSMenu()
        sub.autoenablesItems = false

        guard state.isUp else {
            let item = NSMenuItem(title: "Hub is not running", action: nil, keyEquivalent: "")
            item.image = Self.glyph("bolt.horizontal.circle", size: 14)
            item.isEnabled = false
            return item
        }
        if !state.isProvisioned {
            sub.addItem(Self.caption("No token, so every request is refused."))
            sub.addItem(Self.caption("Run: jstack-host status"))
            return Self.opener("No Access", symbol: "lock", submenu: sub)
        }
        if state.unauthorized {
            sub.addItem(Self.caption("The token on disk was refused by the hub."))
            return Self.opener("No Access", symbol: "lock", submenu: sub)
        }

        let sorted = state.sessions.sorted {
            ($0.live == true ? 0 : 1, $0.title) < ($1.live == true ? 0 : 1, $1.title)
        }
        guard !sorted.isEmpty else {
            let item = NSMenuItem(title: "Nothing running", action: nil, keyEquivalent: "")
            item.image = Self.glyph("moon.zzz", size: 14)
            item.isEnabled = false
            return item
        }
        for session in sorted {
            let emoji = (session.emoji ?? "").isEmpty ? "" : "\(session.emoji!) "
            let row = NSMenuItem(title: "\(emoji)\(session.title)",
                                 action: nil, keyEquivalent: "")
            // The dot is the state, and it is an icon rather than a character
            // in the title so every row's text starts at the same x — a list
            // whose left edge moves with the status is one you cannot scan.
            row.image = Self.dot(live: session.live == true,
                                 idle: session.running == true
                                       || session.onMac == true
                                       || session.managed == true)

            // Kill hangs off the process rather than sitting beside its name:
            // a one-click kill in a list you are scrolling is a session ended
            // by the mouse passing over it.
            let actions = NSMenu()
            actions.autoenablesItems = false
            let kill = Self.action("Kill", #selector(doKill), self, symbol: "xmark.circle")
            kill.representedObject = session
            actions.addItem(kill)
            row.submenu = actions
            sub.addItem(row)
        }
        // Kill All last and behind a separator, so the pointer travelling down
        // the list of sessions does not arrive on it.
        sub.addItem(.separator())
        let killAll = Self.action("Kill All", #selector(doKillAll), self,
                                  symbol: "xmark.octagon")
        killAll.representedObject = sorted
        sub.addItem(killAll)

        // Same shape as the machine's row: a count, and the split underneath.
        //
        // The two states are what you opened the menu to tell apart — a
        // machine with five sessions all idle and one with five mid-turn are
        // not the same machine, and a single total says the same thing about
        // both. They partition the list rather than nest: working is a subset
        // of running everywhere else in this API, and counting it twice here
        // would leave the numbers refusing to add up to the rows beneath them.
        let working = sorted.filter { $0.live == true }.count
        let idle = sorted.count - working
        let subtitle: String
        switch (working, idle) {
        case (0, _): subtitle = "\(idle) running"
        case (_, 0): subtitle = "\(working) working"
        default:     subtitle = "\(working) working, \(idle) running"
        }
        let title = "\(sorted.count) "
            + (sorted.count == 1 ? "Process" : "Processes")
        let item = Self.opener(title, symbol: "person.2", submenu: sub)
        item.attributedTitle = Self.twoLine(title, subtitle)
        item.image = Self.glyph("person.2", size: 26)
        return item
    }

    /// The header row's two lines: what the machine is, and what it is doing.
    ///
    /// An attributed title rather than a custom view. A menu item with a view
    /// stops being a menu item — it loses the system's highlight, its
    /// keyboard handling and its submenu triangle, all of which would then
    /// have to be redrawn by hand and would still be slightly wrong. Two
    /// paragraphs and a taller image get the same result and stay native.
    private static func twoLine(_ title: String, _ subtitle: String) -> NSAttributedString {
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineSpacing = 1
        let out = NSMutableAttributedString(string: title, attributes: [
            .font: NSFont.systemFont(ofSize: NSFont.systemFontSize, weight: .semibold),
            .foregroundColor: NSColor.labelColor,
            .paragraphStyle: paragraph,
        ])
        guard !subtitle.isEmpty else { return out }
        out.append(NSAttributedString(string: "\n" + subtitle, attributes: [
            .font: NSFont.systemFont(ofSize: NSFont.smallSystemFontSize),
            .foregroundColor: NSColor.secondaryLabelColor,
            .paragraphStyle: paragraph,
        ]))
        return out
    }

    /// A row whose job is to open something.
    private static func opener(_ title: String, symbol: String,
                               submenu: NSMenu) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.image = glyph(symbol, size: 14)
        item.submenu = submenu
        return item
    }

    /// A filled dot for a session that is producing, a hollow one for a session
    /// that is up but quiet, nothing for the rest.
    private static func dot(live: Bool, idle: Bool) -> NSImage? {
        guard live || idle else { return blank(width: 10) }
        let name = live ? "circle.fill" : "circle"
        let config = NSImage.SymbolConfiguration(pointSize: 7, weight: .semibold)
        let image = NSImage(systemSymbolName: name, accessibilityDescription:
                                live ? "running" : "idle")?
            .withSymbolConfiguration(config)
        image?.isTemplate = true
        return image ?? blank(width: 10)
    }

    /// Occupies the icon column so a row with no dot still lines up with one
    /// that has.
    private static func blank(width: CGFloat) -> NSImage {
        let image = NSImage(size: NSSize(width: width, height: 1))
        image.isTemplate = true
        return image
    }

    private static func glyph(_ symbol: String, size: CGFloat) -> NSImage? {
        let config = NSImage.SymbolConfiguration(pointSize: size, weight: .regular)
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)
            ?? NSImage(systemSymbolName: "desktopcomputer", accessibilityDescription: nil)
        let out = image?.withSymbolConfiguration(config)
        out?.isTemplate = true
        return out
    }

    // MARK: Items

    /// A row that says something rather than does something.
    ///
    /// Disabled so it cannot be clicked, but drawn with an explicit color:
    /// AppKit greys a disabled item to the point of looking broken, and these
    /// are the content of the menu, not a dead option in it.
    private static func caption(_ text: String, dim: Bool = true) -> NSMenuItem {
        let item = NSMenuItem(title: text, action: nil, keyEquivalent: "")
        item.isEnabled = false
        item.attributedTitle = NSAttributedString(string: text, attributes: [
            .font: NSFont.menuFont(ofSize: NSFont.systemFontSize),
            .foregroundColor: dim ? NSColor.secondaryLabelColor : NSColor.labelColor,
        ])
        return item
    }

    private static func action(_ title: String, _ selector: Selector,
                               _ target: AnyObject,
                               symbol: String? = nil,
                               indent: Int = 0) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: selector, keyEquivalent: "")
        item.target = target
        item.isEnabled = true
        item.indentationLevel = indent
        if let symbol { item.image = glyph(symbol, size: 13) }
        return item
    }

    // MARK: Actions

    @objc private func doRestart() {
        HostControl.restart()
        after(1.5) { self.refresh() }
    }

    @objc private func doStop() {
        HostControl.stop()
        after(1.0) { self.refresh() }
    }

    @objc private func doStart() {
        HostControl.start()
        after(2.0) { self.refresh() }
    }

    /// Kill a session, after asking.
    ///
    /// A confirmation because this is not undoable and the menu is a place the
    /// pointer passes through: the transcript survives, but the turn in flight
    /// does not, and "which one was highlighted" is not a question to answer
    /// after the fact.
    @objc private func doKill(_ sender: NSMenuItem) {
        guard let session = sender.representedObject as? Session,
              let sid = session.sessionId, !sid.isEmpty,
              let token = HostAgent.token() else { return }

        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "Kill \(session.title)?"
        alert.informativeText = "It stops mid-turn — no clean exit, no review. "
            + "The transcript is kept, so it can be resumed later."
        alert.addButton(withTitle: "Kill")
        alert.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return }

        probe.kill(sid: sid, token: token) { [weak self] ok, detail in
            if !ok {
                let failed = NSAlert()
                failed.alertStyle = .warning
                failed.messageText = "Could not kill \(session.title)"
                failed.informativeText = detail
                failed.runModal()
            }
            self?.refresh()
        }
    }

    /// Kill everything on the list.
    ///
    /// Spelled out in the confirmation, count and all, because this is the one
    /// control in the menu that can end work you were not thinking about —
    /// including the session you are reading this from.
    @objc private func doKillAll(_ sender: NSMenuItem) {
        guard let sessions = sender.representedObject as? [Session],
              !sessions.isEmpty, let token = HostAgent.token() else { return }
        let sids = sessions.compactMap { $0.sessionId }.filter { !$0.isEmpty }
        guard !sids.isEmpty else { return }

        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "Kill all \(sids.count) processes?"
        alert.informativeText = "Every one stops mid-turn — no clean exit, no "
            + "review. This includes any session you are currently talking to. "
            + "Transcripts are kept, so they can be resumed later."
        alert.addButton(withTitle: "Kill All")
        alert.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return }

        let group = DispatchGroup()
        var failures: [String] = []
        for sid in sids {
            group.enter()
            probe.kill(sid: sid, token: token) { ok, detail in
                if !ok { failures.append("\(sid.prefix(8)): \(detail)") }
                group.leave()
            }
        }
        group.notify(queue: .main) { [weak self] in
            if !failures.isEmpty {
                let failed = NSAlert()
                failed.alertStyle = .warning
                failed.messageText = "\(failures.count) of \(sids.count) did not stop"
                failed.informativeText = failures.joined(separator: "\n")
                failed.runModal()
            }
            self?.refresh()
        }
    }

    /// Opens the client app, or brings it forward if it is already running.
    ///
    /// Activation rather than a second copy: two instances of a client that
    /// each hold their own connection to a hub is a way to be told two
    /// different things about one machine. Activation alone only raises
    /// whatever window was already frontmost, though — `BoardRaise` is what
    /// gets the board itself in front of a thread window left on top.
    @objc private func doOpenApp() {
        guard let url = RemoteApp.url else { return }
        NSWorkspace.shared.openApplication(at: url,
                                           configuration: NSWorkspace.OpenConfiguration())
        BoardRaise.send()
    }

    @objc private func doLogs() {
        NSWorkspace.shared.open(HostAgent.logDirectory())
    }

    @objc private func doQuit() { NSApp.terminate(nil) }

    /// Mint an enrolment code and show it. A code rather than the raw token:
    /// it expires, it names the device before the device connects, and revoking
    /// it later does not re-key everything else on the host.
    @objc private func doPair() {
        guard let binary = HostControl.hostBinary else { return }
        NSApp.activate(ignoringOtherApps: true)

        let ask = NSAlert()
        ask.messageText = "Pair a device"
        ask.informativeText = "What should this host call it?"
        ask.addButton(withTitle: "Get a Code")
        ask.addButton(withTitle: "Cancel")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 240, height: 24))
        field.stringValue = "My device"
        ask.accessoryView = field
        ask.window.initialFirstResponder = field
        guard ask.runModal() == .alertFirstButtonReturn else { return }

        let name = field.stringValue.trimmingCharacters(in: .whitespaces)
        let result = HostControl.run(binary,
                                     ["pair", name.isEmpty ? "My device" : name, "--json"])

        guard result.code == 0, let minted = MintedPairing(json: result.out) else {
            // Nothing to draw — say what the host said, verbatim. This is also
            // the path for a host binary too old to answer `--json`.
            let failed = NSAlert()
            failed.alertStyle = .warning
            failed.messageText = "Could not mint a code"
            failed.informativeText = result.out.trimmingCharacters(in: .whitespacesAndNewlines)
            failed.runModal()
            return
        }

        // One action, not a menu of addresses. The QR carries the address and
        // the code together — the exact link the app already answers — so the
        // person points a camera instead of choosing which of three URLs
        // "fits". The typed path stays underneath as the fallback, with ONE
        // address in it: the first one, which the host orders reachable-first.
        let shown = NSAlert()
        shown.messageText = "Pair \(minted.name)"
        shown.informativeText = minted.link != nil
            ? "Point that device's camera at the code — it opens the app and "
            + "connects on its own.\n\nBy hand instead: in the app, "
            + "Instances › Add a Mac — address \(minted.firstAddress ?? "?"), "
            + "then the code. Good for \(minted.validFor)."
            : "This Mac could not work out an address a second device can "
            + "reach — connect both machines to the same network and mint a "
            + "new code. This one is good for \(minted.validFor)."
        shown.accessoryView = pairAccessory(minted)
        shown.addButton(withTitle: "Done")
        shown.addButton(withTitle: "Copy Code")
        if shown.runModal() == .alertSecondButtonReturn {
            // The code alone, not the whole message — what gets pasted into the
            // app is the code, and a paste that carries the explanation with it
            // is a paste that fails.
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(minted.code, forType: .string)
        }
    }

    /// The QR above the code it encodes. The code is drawn even though it is
    /// inside the QR: the fallback for a device with no camera to point is
    /// typing, and typing needs something legible to type.
    private func pairAccessory(_ minted: MintedPairing) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 10

        if let link = minted.link, let qr = Self.qrImage(link, side: 180) {
            let image = NSImageView(image: qr)
            image.imageScaling = .scaleNone
            stack.addArrangedSubview(image)
        }

        let code = NSTextField(labelWithString: minted.code)
        code.font = .monospacedSystemFont(ofSize: 22, weight: .semibold)
        code.isSelectable = true
        stack.addArrangedSubview(code)

        stack.frame = NSRect(x: 0, y: 0, width: 260,
                             height: stack.fittingSize.height)
        return stack
    }

    /// `string` as a QR the size a dialog wants. Nearest-neighbour scaling by
    /// transform, not by resize — a QR with soft edges is a QR a phone camera
    /// hunts on.
    static func qrImage(_ string: String, side: CGFloat) -> NSImage? {
        guard let data = string.data(using: .ascii),
              let filter = CIFilter(name: "CIQRCodeGenerator") else { return nil }
        filter.setValue(data, forKey: "inputMessage")
        filter.setValue("M", forKey: "inputCorrectionLevel")
        guard let output = filter.outputImage else { return nil }
        let scale = (side / output.extent.width).rounded(.down)
        let scaled = output.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        let rep = NSCIImageRep(ciImage: scaled)
        let image = NSImage(size: rep.size)
        image.addRepresentation(rep)
        return image
    }

    // MARK: Settings

    @objc private func doToggleHubLogin(_ sender: NSMenuItem) {
        setLogin(HostAgent.label, sender, what: "the hub")
    }

    @objc private func doToggleBarLogin(_ sender: NSMenuItem) {
        setLogin(MenuBarAgent.label, sender, what: "the menu bar app")
    }

    /// Flip the flag, and say so if the file would not take it.
    ///
    /// Silence on failure is the thing to avoid here: the row would redraw from
    /// the plist on the next open and simply appear not to have been clicked,
    /// which is indistinguishable from a menu that ignores you.
    private func setLogin(_ label: String, _ sender: NSMenuItem, what: String) {
        let wanted = sender.state != .on
        guard LoginAgent.setStartsAtLogin(label, wanted) else {
            let failed = NSAlert()
            failed.alertStyle = .warning
            failed.messageText = "Could not change the login setting"
            failed.informativeText = "\(LoginAgent.plistURL(label).path) could "
                + "not be written."
            NSApp.activate(ignoringOtherApps: true)
            failed.runModal()
            return
        }
        sender.state = wanted ? .on : .off
        // Said out loud once, because a checkbox that ticks instantly reads as
        // something that happened instantly — and this one has not happened yet.
        if !wanted {
            let note = NSAlert()
            note.messageText = "\(what.prefix(1).uppercased())\(what.dropFirst()) "
                + "will not start at the next login"
            note.informativeText = "Whatever is running now keeps running. "
                + "Turn it back on here."
            NSApp.activate(ignoringOtherApps: true)
            note.runModal()
        }
    }

    /// The state of everything, as text, for pasting into a message when
    /// something is wrong. The token's *path* and whether it reads — never its
    /// value: this goes to a clipboard, and a clipboard goes anywhere.
    @objc private func doCopyDiagnostics() {
        var lines = [
            "JStack host — \(Machine.name)",
            "hub        \(state.headline)",
            "agent      \(HostAgent.label)"
                + (HostAgent.isInstalled ? "" : " (no plist)"),
            "login      hub \(HostAgent.isInstalled && LoginAgent.startsAtLogin(HostAgent.label) ? "yes" : "no")"
                + ", menu bar \(LoginAgent.startsAtLogin(MenuBarAgent.label) ? "yes" : "no")",
            "bind       \(HostAgent.bind() ?? "not recorded")",
            "state      \(HostAgent.stateDir().path)",
            "token      \(HostAgent.tokenPath().path)"
                + (HostAgent.token() == nil ? " — missing" : " — present"),
        ]
        if let identity = state.identity {
            lines.append("host_id    \(identity.hostId ?? "?")")
            lines.append("profile    \(identity.profile ?? "?")")
        }
        lines.append("sessions   \(state.sessions.count) "
                     + "(\(state.liveCount) working)")
        if state.unauthorized { lines.append("auth       token refused by the hub") }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(lines.joined(separator: "\n"), forType: .string)
    }

    private func after(_ seconds: TimeInterval, _ block: @escaping () -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: block)
    }
}

extension StatusController: NSMenuDelegate {
    /// Poll on open as well as on the timer. The ten-second tick is for the
    /// icon; a menu being opened is someone asking right now, and showing them
    /// a board up to ten seconds stale is the thing that makes an indicator
    /// stop being believed.
    func menuWillOpen(_ menu: NSMenu) { refresh() }
}

// MARK: - The app

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var controller: StatusController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // No Dock tile, no menu bar of its own — this app *is* its status item.
        // Set in code as well as in Info.plist so a binary run straight out of
        // the build directory behaves the same as the installed bundle.
        NSApp.setActivationPolicy(.accessory)
        controller = StatusController()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
