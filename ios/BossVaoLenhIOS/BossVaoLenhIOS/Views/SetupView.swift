import SwiftUI

struct SetupView: View {
    @EnvironmentObject private var model: BossViewModel
    @State private var serverURL = ""
    @State private var password = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://boss.example.com", text: $serverURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    SecureField("Mật khẩu Cloud", text: $password)
                } header: {
                    Text("Boss Cloud")
                } footer: {
                    Text("Có thể nhập địa chỉ HTTPS hoặc địa chỉ IP:8765. Cloud tiếp tục chạy kể cả khi iPhone và PC tắt.")
                }

                if !model.errorMessage.isEmpty {
                    Section {
                        Text(model.errorMessage)
                            .foregroundStyle(.red)
                    }
                }

                Section {
                    Button {
                        Task {
                            _ = await model.connect(serverURL: serverURL, password: password)
                        }
                    } label: {
                        HStack {
                            Spacer()
                            if model.isLoading {
                                ProgressView()
                            } else {
                                Text("KẾT NỐI BOSS")
                                    .fontWeight(.bold)
                            }
                            Spacer()
                        }
                    }
                    .disabled(model.isLoading)
                }
            }
            .navigationTitle("Boss Vào Lệnh")
            .onAppear {
                serverURL = model.serverURL
            }
        }
    }
}
