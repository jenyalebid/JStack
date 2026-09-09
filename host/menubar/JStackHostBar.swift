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
        button.image = Self.glyph(unprovisioned
            ? "desktopcomputer.trianglebadge.exclamationmark"
            : "desktopcomputer")
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

        menu.addItem(Self.caption(state.summary))
        menu.addItem(.separator())
        for row in activeRows() { menu.addItem(row) }
        menu.addItem(.separator())

        // Only when there is an agent to operate. A host running in a terminal
        // is stopped by the terminal it is running in, and a Stop button that
        // boots out a job that does not exist is a button that lies.
        if state.installed {
            if state.isUp {
                menu.addItem(Self.action("Restart Host", #selector(doRestart), self))
                menu.addItem(Self.action("Stop Hosting", #selector(doStop), self))
            } else {
                menu.addItem(Self.action("Start Hosting", #selector(doStart), self))
            }
        }
        if state.isUp, HostControl.hostBinary != nil {
            menu.addItem(Self.action("Pair a Device…", #selector(doPair), self))
        }

        menu.addItem(.separator())
        if FileManager.default.fileExists(atPath: HostAgent.logDirectory().path) {
            menu.addItem(Self.action("Open Log Folder", #selector(doLogs), self))
        }
        menu.addItem(Self.action("Refresh Now", #selector(doRefresh), self))

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
    private func activeRows() -> [NSMenuItem] {
        guard state.isUp else { return [] }
        if !state.isProvisioned {
            return [Self.caption("No token, so every request is refused."),
                    Self.caption("Run: jstack-host status")]
        }
        if state.unauthorized {
            return [Self.caption("The token on disk was refused by the host.")]
        }
        if state.sessions.isEmpty {
            return [Self.caption("Nothing running")]
        }
        let sorted = state.sessions.sorted {
            ($0.live == true ? 0 : 1, $0.title) < ($1.live == true ? 0 : 1, $1.title)
        }
        let header = Self.caption("Active — \(sorted.count)")
        return [header] + sorted.map { session in
            let emoji = (session.emoji ?? "").isEmpty ? "" : "\(session.emoji!) "
            return Self.caption("  \(session.mark) \(emoji)\(session.title)",
                                dim: session.live != true)
        }
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
                               _ target: AnyObject) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: selector, keyEquivalent: "")
        item.target = target
        item.isEnabled = true
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
