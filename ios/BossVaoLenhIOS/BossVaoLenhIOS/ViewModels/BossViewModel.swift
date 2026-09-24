import Foundation

@MainActor
final class BossViewModel: ObservableObject {
    @Published var status: BossStatus?
    @Published var errorMessage = ""
    @Published var actionMessage = ""
    @Published var isLoading = false
    @Published var isConfigured = false

    private(set) var serverURL = ""
    private(set) var password = ""
    private var pollingStarted = false

    init() {
        serverURL = UserDefaults.standard.string(forKey: "bossServerURL") ?? ""
        password = KeychainStore.loadPassword()
        isConfigured = !serverURL.isEmpty && !password.isEmpty
    }

    private var client: BossAPIClient {
        BossAPIClient(baseURL: serverURL, password: password)
    }

    func connect(serverURL: String, password: String) async -> Bool {
        let trimmedURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedPassword = password.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedURL.isEmpty, !trimmedPassword.isEmpty else {
            errorMessage = "Nhập địa chỉ Boss Cloud và mật khẩu."
            return false
        }

        isLoading = true
        defer { isLoading = false }

        do {
            let temp = BossAPIClient(baseURL: trimmedURL, password: trimmedPassword)
            let fetched = try await temp.status()
            self.serverURL = trimmedURL
            self.password = trimmedPassword
            UserDefaults.standard.set(trimmedURL, forKey: "bossServerURL")
            KeychainStore.savePassword(trimmedPassword)
            status = fetched
            errorMessage = ""
            isConfigured = true
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func disconnect() {
        UserDefaults.standard.removeObject(forKey: "bossServerURL")
        KeychainStore.clear()
        serverURL = ""
        password = ""
        status = nil
        errorMessage = ""
        actionMessage = ""
        isConfigured = false
    }

    func refresh() async {
        guard isConfigured else { return }
        do {
            status = try await client.status()
            errorMessage = ""
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func startPolling() async {
        guard !pollingStarted else { return }
        pollingStarted = true
        while !Task.isCancelled {
            if isConfigured {
                await refresh()
            }
            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
        pollingStarted = false
    }

    func saveSettings(
        bet1: Double,
        bet2: Double,
        startBalance: Double,
        payoutPercent: Double,
        telegramEnabled: Bool
    ) async {
        guard isConfigured else { return }
        isLoading = true
        actionMessage = "Đang lưu..."
        defer { isLoading = false }
        do {
            try await client.saveSettings(
                BossSettingsPayload(
                    bet1: bet1,
                    bet2: bet2,
                    startBalance: startBalance,
                    payoutPercent: payoutPercent,
                    telegramEnabled: telegramEnabled
                )
            )
            actionMessage = "Đã lưu."
            await refresh()
        } catch {
            actionMessage = "Lỗi: \(error.localizedDescription)"
        }
    }

    func testTelegram() async {
        guard isConfigured else { return }
        isLoading = true
        actionMessage = "Đang gửi Telegram..."
        defer { isLoading = false }
        do {
            try await client.testTelegram()
            actionMessage = "TEST TELEGRAM đã gửi."
            await refresh()
        } catch {
            actionMessage = "Lỗi: \(error.localizedDescription)"
        }
    }
}
