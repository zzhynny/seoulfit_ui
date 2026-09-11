import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/models/travel_state.dart';
import 'package:seoulfit_ui/screens/trip/day_planner_screen.dart';

void main() {
  const seeded = [
    DaySpec(day: 1, region: 'jongno', interest: 'Shopping'),
    DaySpec(day: 2, region: 'myeongdong', interest: 'Shopping'),
    DaySpec(day: 3, region: 'hongdae', interest: 'Shopping'),
  ];

  Widget harness(List<DaySpec> specs, {ValueChanged<List<DaySpec>>? onSubmit}) =>
      MaterialApp(
        home: DayPlannerScreen(initial: specs, onSubmit: onSubmit ?? (_) {}),
      );

  testWidgets('opens with one row per day, already filled in', (tester) async {
    await tester.pumpWidget(harness(seeded));
    expect(find.text('Day 1'), findsOneWidget);
    expect(find.text('Day 3'), findsOneWidget);
    expect(find.text('Jongno'), findsOneWidget);
    expect(find.text('Shopping'), findsNWidgets(3));
  });

  testWidgets('a seven day trip shows seven rows', (tester) async {
    final week = List.generate(
      7, (i) => DaySpec(day: i + 1, region: 'jongno', interest: 'Shopping'));
    await tester.pumpWidget(harness(week));
    expect(find.textContaining('Day '), findsNWidgets(7));
  });

  testWidgets('submits what the rows currently hold', (tester) async {
    List<DaySpec>? sent;
    await tester.pumpWidget(harness(seeded, onSubmit: (v) => sent = v));

    await tester.tap(find.byKey(const ValueKey('interest-2')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Food & Cafes').last);
    await tester.pumpAndSettle();

    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();

    expect(sent, isNotNull);
    expect(sent![1].interest, 'Food & Cafes');
    expect(sent![0].interest, 'Shopping');
  });
}
