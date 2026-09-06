@Tags(['backend'])
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/config/api_base.dart';
import 'package:seoulfit_ui/services/api_service.dart';

/// Proves the backend layer copied in from the Flutter app is wired up inside
/// seoulfit_ui: deps resolve, `apiBase` points somewhere, and a real `/chat`
/// turn round-trips into a parsed `TravelState`.
///
/// Run it with the backend up and the base URL pinned:
///
///   cd seoulfit_flutter/backend && ./venv/bin/uvicorn api:app --port 8000
///   flutter test --dart-define=API_BASE_URL=http://localhost:8000 \
///       test/backend_smoke_test.dart
///
/// The dart-define is required, not optional: `flutter test` reports
/// `defaultTargetPlatform == android`, so the unpinned [apiBase] resolves to
/// the emulator's host alias `10.0.2.2`, which does not route from the host
/// machine and hangs until the 30s client timeout.
void main() {
  test('apiBase resolves to a bare origin', () {
    expect(apiBase, isNotEmpty);
    expect(apiBase, isNot(endsWith('/')));
  });

  test('a chat turn round-trips into a parsed TravelState', () async {
    final state = await ApiService().chat(null);

    // The greeting turn must come back with something to render and the
    // backend's slot machinery intact.
    expect(state.reply, isNotNull);
    expect(state.reply, isNotEmpty);
    expect(state.currentStep, isNotEmpty);
    expect(state.confirmed, isFalse);
    expect(state.slots.keys, contains('travel_dates'));

    // The generated thread id has to clear the backend's own 16-128 char
    // guard, or every chat turn 422s before it reaches the graph.
    expect(ApiService().threadId.length, greaterThanOrEqualTo(16));
  }, timeout: const Timeout(Duration(seconds: 60)));
}
