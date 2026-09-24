import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/models/travel_state.dart';
import 'package:seoulfit_ui/screens/trip/day_planner_screen.dart';
import 'package:seoulfit_ui/services/api_service.dart';

/// Stands in for the backend answering POST /day-plan with a non-200: real
/// [ApiService] methods throw `Exception('Backend error $code: $body')` on
/// any status other than 200, so this reproduces that shape without a
/// network call.
class _ThrowingApi extends ApiService {
  _ThrowingApi(this.statusCode);

  final int statusCode;

  @override
  Future<TravelState> getState() async => const TravelState(
        daySpecs: [DaySpec(day: 1, region: 'jongno')],
      );

  @override
  Future<TravelState> postDayPlan(List<DaySpec> days) async {
    throw Exception('Backend error $statusCode: nope');
  }
}

void main() {
  Future<void> pumpAndSubmit(
    WidgetTester tester, {
    required int statusCode,
    required VoidCallback onDone,
    required VoidCallback onStale,
    required VoidCallback onFailed,
  }) async {
    await tester.pumpWidget(MaterialApp(
      home: DayPlannerLoader(
        api: _ThrowingApi(statusCode),
        onDone: onDone,
        onStale: onStale,
        onFailed: onFailed,
      ),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
  }

  testWidgets('a rejected submit is surfaced as an error, not swallowed',
      (tester) async {
    var doneCalled = false;
    var staleCalled = false;
    var failedCalled = false;

    // 400: an unknown region/interest or a wrong day count — a bug on this
    // screen's side, not a stale session.
    await pumpAndSubmit(
      tester,
      statusCode: 400,
      onDone: () => doneCalled = true,
      onStale: () => staleCalled = true,
      onFailed: () => failedCalled = true,
    );

    // Before the fix this exception went unhandled: onDone never ran, but
    // neither did anything else — Continue looked dead. Now it must reach
    // onFailed specifically.
    expect(doneCalled, isFalse);
    expect(staleCalled, isFalse);
    expect(failedCalled, isTrue);
  });

  testWidgets('a 409 (thread moved past day_plan) sends the traveller back to chat',
      (tester) async {
    var doneCalled = false;
    var staleCalled = false;
    var failedCalled = false;

    await pumpAndSubmit(
      tester,
      statusCode: 409,
      onDone: () => doneCalled = true,
      onStale: () => staleCalled = true,
      onFailed: () => failedCalled = true,
    );

    expect(doneCalled, isFalse);
    expect(staleCalled, isTrue);
    expect(failedCalled, isFalse);
  });
}
