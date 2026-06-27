import SwiftUI

@main
struct SafeWordApp: App {
    @StateObject private var model: AppViewModel

    init() {
        let environment = AppEnvironment.live()
        _model = StateObject(wrappedValue: AppViewModel(environment: environment))
        self.environment = environment
    }

    private let environment: AppEnvironment

    var body: some Scene {
        WindowGroup {
            RootView(model: model, environment: environment)
                .task { model.bootstrap() }
        }
    }
}
