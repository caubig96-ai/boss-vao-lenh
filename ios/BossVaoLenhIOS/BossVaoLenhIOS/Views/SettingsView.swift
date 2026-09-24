import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var model: BossViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var bet1 = ""
    @State private var bet2 = ""
    @State private var startBalance = ""
    @State private var payout = ""
    @State private var telegramEnabled = true
    @State private var loaded = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Tiền lệnh") {
                    numberField("Lệnh 1 (USDT)", text: $bet1)
                    numberField("Lệnh 2 (USDT)", text: $bet2)
                    numberField("Vốn đầu ngày", text: $startBalance)
                    numberField("Trả thưởng (%)", text: $payout)
                    Toggle("Gửi Telegram", isOn: $telegramEnabled)
                }

                Section {
                    Button("LƯU CÀI ĐẶT") {
                        Task { await save() }
                    }
                    .disabled(model.isLoading)

                    Button("TEST TELEGRAM") {
                        Task { await model.testTelegram() }
                    }
                    .disabled(model.isLoading)
                }

                if !model.actionMessage.isEmpty {
                    Section {
                        Text(model.actionMessage)
                            .foregroundStyle(model.actionMessage.hasPrefix("Lỗi") ? .red : .secondary)
                    }
                }

                Section("Cloud") {
                    LabeledContent("Địa chỉ", value: model.serverURL)
                    LabeledContent("Telegram", value: model.status?.telegramConfigured == true ? "Đã cấu hình" : "Chưa cấu hình")
                    Button("Ngắt kết nối iPhone", role: .destructive) {
                        model.disconnect()
                        dismiss()
                    }
                } footer: {
                    Text("Ngắt kết nối iPhone không dừng Boss Cloud. Server vẫn tiếp tục chạy và Telegram vẫn tiếp tục gửi.")
                }
            }
            .navigationTitle("Cài đặt")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Xong") { dismiss() }
                }
            }
            .onAppear { loadFields() }
        }
    }

    @ViewBuilder
    private func numberField(_ title: String, text: Binding<String>) -> some View {
        TextField(title, text: text)
            .keyboardType(.decimalPad)
    }

    private func loadFields() {
        guard !loaded, let s = model.status else { return }
        bet1 = String(format: "%.2f", s.bet1)
        bet2 = String(format: "%.2f", s.bet2)
        startBalance = String(format: "%.2f", s.startBalance)
        payout = String(format: "%.2f", s.payoutPercent)
        telegramEnabled = s.telegramEnabled
        loaded = true
    }

    private func save() async {
        guard let v1 = Double(bet1.replacingOccurrences(of: ",", with: ".")),
              let v2 = Double(bet2.replacingOccurrences(of: ",", with: ".")),
              let start = Double(startBalance.replacingOccurrences(of: ",", with: ".")),
              let pay = Double(payout.replacingOccurrences(of: ",", with: ".")) else {
            model.actionMessage = "Lỗi: các ô tiền phải là số."
            return
        }
        await model.saveSettings(
            bet1: v1,
            bet2: v2,
            startBalance: start,
            payoutPercent: pay,
            telegramEnabled: telegramEnabled
        )
    }
}
