import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var model: BossViewModel
    @State private var showSettings = false

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 4), count: 10)

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 14) {
                    connectionCard
                    signalCard
                    statsCard
                    historyCard

                    if !model.errorMessage.isEmpty {
                        Text(model.errorMessage)
                            .font(.footnote)
                            .foregroundStyle(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding()
                            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14))
                    }
                }
                .padding()
            }
            .background(Color.black)
            .navigationTitle("Boss 5 Nến")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape.fill")
                    }
                }
            }
            .refreshable {
                await model.refresh()
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
                    .environmentObject(model)
            }
        }
    }

    private var connectionCard: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Circle()
                    .fill(model.status?.connected == true ? Color.green : Color.orange)
                    .frame(width: 10, height: 10)
                Text(model.status?.connected == true ? "Cloud đang chạy" : "Cloud đang chờ dữ liệu")
                    .fontWeight(.semibold)
                Spacer()
            }
            Text(model.status?.sourceLabel ?? "Đang kết nối...")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(model.serverURL)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .cardStyle()
    }

    private var signalCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("5 kết quả BTC Up/Down 5m gần nhất")
                .font(.caption)
                .foregroundStyle(.secondary)

            HStack(spacing: 10) {
                let colors = model.status?.colors ?? []
                ForEach(0..<5, id: \.self) { index in
                    Circle()
                        .fill(candleColor(index < colors.count ? colors[index] : ""))
                        .frame(maxWidth: .infinity)
                        .aspectRatio(1, contentMode: .fit)
                        .overlay(
                            Circle()
                                .stroke(Color.white.opacity(0.08), lineWidth: 1)
                        )
                }
            }

            HStack(alignment: .bottom) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Lệnh vòng kế tiếp")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(model.status?.recommendationText ?? "CHỜ")
                        .font(.title.bold())
                        .foregroundStyle(recommendationColor)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 4) {
                    Text(model.status?.frame ?? "--:--–--:--")
                        .fontWeight(.semibold)
                    Text("Lệnh \(model.status?.currentStep ?? 1) • \(money(model.status?.nextBet ?? 0))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .cardStyle()
    }

    private var statsCard: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
            statTile("Thắng hôm nay", value: "\(model.status?.wins ?? 0)", color: .green)
            statTile("Thua hôm nay", value: "\(model.status?.losses ?? 0)", color: .red)
            statTile("Lãi / lỗ", value: money(model.status?.dailyPnl ?? 0), color: pnlColor)
            statTile("Số dư cuối ngày", value: money(model.status?.endBalance ?? 0), color: .primary)
        }
    }

    private var historyCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading) {
                    Text("100 lệnh gần nhất")
                        .fontWeight(.semibold)
                    Text("V = thắng • X = thua")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button {
                    Task { await model.refresh() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
            }

            LazyVGrid(columns: columns, spacing: 4) {
                let marks = paddedHistory
                ForEach(0..<100, id: \.self) { index in
                    let mark = marks[index]
                    Text(mark.isEmpty ? "·" : mark)
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .frame(maxWidth: .infinity)
                        .aspectRatio(1, contentMode: .fit)
                        .background(historyColor(mark), in: RoundedRectangle(cornerRadius: 5))
                        .foregroundStyle(historyTextColor(mark))
                }
            }

            Divider()

            HStack {
                Text("Telegram")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(model.status?.telegramStatus ?? "Chưa có trạng thái")
                    .font(.caption)
                    .multilineTextAlignment(.trailing)
            }
        }
        .cardStyle()
    }

    private var paddedHistory: [String] {
        let history = Array((model.status?.history ?? []).suffix(100))
        return Array(repeating: "", count: max(0, 100 - history.count)) + history
    }

    private var recommendationColor: Color {
        switch model.status?.recommendation {
        case "G": return .green
        case "R": return .red
        default: return .secondary
        }
    }

    private var pnlColor: Color {
        let pnl = model.status?.dailyPnl ?? 0
        return pnl > 0 ? .green : pnl < 0 ? .red : .primary
    }

    private func candleColor(_ value: String) -> Color {
        value == "G" ? .green : value == "R" ? .red : Color.gray.opacity(0.25)
    }

    private func historyColor(_ mark: String) -> Color {
        mark == "V" ? Color.green.opacity(0.22) : mark == "X" ? Color.red.opacity(0.22) : Color.white.opacity(0.04)
    }

    private func historyTextColor(_ mark: String) -> Color {
        mark == "V" ? .green : mark == "X" ? .red : .secondary
    }

    private func statTile(_ title: String, value: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title3.bold())
                .foregroundStyle(color)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 14))
    }

    private func money(_ value: Double) -> String {
        String(format: "%.2f USDT", value)
    }
}

private extension View {
    func cardStyle() -> some View {
        self
            .padding()
            .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 16))
    }
}
