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
import Foundation

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

    /// The machine row's second line. Shorter than `summary` on purpose: it
    /// sits under the machine's name, where the question is "is it up and how
    /// busy", not "how was it configured" — that stays in the tooltip.
    var headline: String {
        guard isUp else {
            return installed ? "Hub is not answering" : "No hub on this Mac"
        }
        guard isProvisioned else { return "Hub running · no token" }
        let live = liveCount
        if live > 0 { return "Hub running · \(live) working" }
        return sessions.isEmpty ? "Hub running · idle"
                                : "Hub running · \(sessions.count) open"
    }

    var summary: String {
        guard isUp else {
            return installed ? "Host is not answering" : "No host on this Mac"
        }
        guard isProvisioned else { return "Hosting — no token" }
        let profile = health?.profile ?? "host"
        // A host serving with no agent and no larger app behind it is
        // `jstack-host serve` — a foreground run in somebody's terminal. Worth
        // saying, because it is the one that will not survive closing that
        // window.
        let how = (installed || embedded) ? "" : " · in a terminal"
        return "Hosting — \(profile) · port \(HostAgent.port())\(how)"
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

            if state.isUp { return loadSessions() }

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
                loadSessions()
            }
        }
    }

    private static var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    /// End a session through the host's own close route — the same one the app
    /// and the board use, so a kill from here goes through the identical
    /// teardown (window closed, end-of-session hook run) instead of a second
    /// implementation that gets one of those wrong.
    func close(sid: String, token: String,
               _ done: @escaping (Bool, String) -> Void) {
        let port = HostAgent.port()
        guard let url = URL(string:
            "http://127.0.0.1:\(port)\(Self.apiPrefix)/sessions/\(sid)/close?review=true")
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
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        for candidate in ["\(home)/.local/bin/jstack-host",
                          "/opt/homebrew/bin/jstack-host",
                          "/usr/local/bin/jstack-host"] {
            if FileManager.default.isExecutableFile(atPath: candidate) { return candidate }
        }
        return nil
    }()
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
        button.toolTip = state.summary
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
        machine.toolTip = state.summary
        machine.submenu = controlsMenu()
        menu.addItem(machine)

        menu.addItem(processesItem())

        // ── The app ─────────────────────────────────────────────────────────
        menu.addItem(.separator())
        if RemoteApp.url != nil {
            menu.addItem(Self.action("jRemote", #selector(doOpenApp), self,
                                     symbol: "macwindow"))
        }
        if FileManager.default.fileExists(atPath: HostAgent.logDirectory().path) {
            menu.addItem(Self.action("Open Log Folder", #selector(doLogs), self,
                                     symbol: "folder"))
        }
        menu.addItem(Self.action("Refresh Now", #selector(doRefresh), self,
                                 symbol: "arrow.triangle.2.circlepath"))

        // No Quit by default. This is the hub's indicator, and the hub runs
        // whether or not anyone is looking at it — so "quit" here never meant
        // "stop the hub", it meant "hide the icon", which is not a thing worth
        // a permanent slot in a menu about the hub. Set JREMOTE_MENUBAR_QUIT=1
        // to put it back; `menubar/install.sh --uninstall` removes it for good.
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
        return sub
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
                                 idle: session.onMac == true || session.managed == true)

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
        // "23 active processes" — the count is the whole point of the row, so
        // it is the row, and the names are what opens off it.
        let title = "\(sorted.count) Active "
            + (sorted.count == 1 ? "Process" : "Processes")
        return Self.opener(title, symbol: "list.bullet.rectangle", submenu: sub)
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

    @objc private func doRefresh() { refresh() }

    /// End a session, after asking.
    ///
    /// A confirmation because this is not undoable and the menu is a place the
    /// pointer passes through: the transcript survives, but the turn in flight
    /// does not, and "which one was highlighted" is not a question to answer
    /// after the fact. `review=true` — the session's own end-of-session hook
    /// runs, the same as closing its window by hand.
    @objc private func doKill(_ sender: NSMenuItem) {
        guard let session = sender.representedObject as? Session,
              let sid = session.sessionId, !sid.isEmpty,
              let token = HostAgent.token() else { return }

        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "Kill \(session.title)?"
        alert.informativeText = "The session ends now. Its transcript is kept, "
            + "so it can be resumed later."
        alert.addButton(withTitle: "Kill")
        alert.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return }

        probe.close(sid: sid, token: token) { [weak self] ok, detail in
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

    /// Opens the client app, or brings it forward if it is already running.
    ///
    /// Activation rather than a second copy: two instances of a client that
    /// each hold their own connection to a hub is a way to be told two
    /// different things about one machine.
    @objc private func doOpenApp() {
        guard let url = RemoteApp.url else { return }
        NSWorkspace.shared.openApplication(at: url,
                                           configuration: NSWorkspace.OpenConfiguration())
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
        let result = HostControl.run(binary, ["pair", name.isEmpty ? "My device" : name])

        let shown = NSAlert()
        shown.messageText = result.code == 0 ? "Enrolment code" : "Could not mint a code"
        shown.informativeText = result.out.trimmingCharacters(in: .whitespacesAndNewlines)
        shown.addButton(withTitle: "Copy")
        shown.addButton(withTitle: "Done")
        if shown.runModal() == .alertFirstButtonReturn {
            // The code alone, not the whole message — what gets pasted into the
            // app is the code, and a paste that carries the explanation with it
            // is a paste that fails.
            let code = result.out.split(whereSeparator: \.isNewline)
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .first { $0.count >= 6 && !$0.contains(" ") } ?? result.out
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(code, forType: .string)
        }
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
