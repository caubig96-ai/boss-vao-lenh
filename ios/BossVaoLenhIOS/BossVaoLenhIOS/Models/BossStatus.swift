import Foundation

struct BossStatus: Codable {
    let connected: Bool
    let status: String?
    let error: String?
    let sourceLabel: String?
    let sourceError: String?
    let telegramStatus: String?
    let telegramConfigured: Bool?
    let colors: [String]
    let pattern: String?
    let recommendation: String?
    let frame: String?
    let currentStep: Int
    let nextBet: Double
    let bet1: Double
    let bet2: Double
    let payoutPercent: Double
    let telegramEnabled: Bool
    let day: String?
    let startBalance: Double
    let dailyPnl: Double
    let endBalance: Double
    let wins: Int
    let losses: Int
    let history: [String]

    var recommendationText: String {
        switch recommendation {
        case "G": return "MUA XANH"
        case "R": return "MUA ĐỎ"
        default: return "KHÔNG KHỚP MẪU"
        }
    }
}

struct BossSettingsPayload: Encodable {
    let bet1: Double
    let bet2: Double
    let startBalance: Double
    let payoutPercent: Double
    let telegramEnabled: Bool

    enum CodingKeys: String, CodingKey {
        case bet1
        case bet2
        case startBalance = "start_balance"
        case payoutPercent = "payout_percent"
        case telegramEnabled = "telegram_enabled"
    }
}

struct BossActionResponse: Decodable {
    let ok: Bool?
    let messageId: Int?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case ok
        case messageId = "message_id"
        case error
    }
}
