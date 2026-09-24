import SwiftUI

@main
struct BossVaoLenhApp: App {
    @StateObject private var model = BossViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .preferredColorScheme(.dark)
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var model: BossViewModel

    var body: some View {
        Group {
            if model.isConfigured {
                DashboardView()
            } else {
                SetupView()
            }
        }
        .task {
            await model.startPolling()
        }
    }
}
