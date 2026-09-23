import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/models/travel_state.dart';
import 'package:seoulfit_ui/screens/trip/day_planner_screen.dart';

void main() {
  const seeded = [
    DaySpec(day: 1, region: 'jongno'),
    DaySpec(day: 2, region: 'myeongdong'),
    DaySpec(day: 3, region: 'hongdae'),
  ];

  Widget harness(List<DaySpec> specs, {ValueChanged<List<DaySpec>>? onSubmit}) =>
      MaterialApp(
        home: DayPlannerScreen(initial: specs, onSubmit: onSubmit ?? (_) {}),
      );

  testWidgets('opens with one row per day, zones named after places', (tester) async {
    await tester.pumpWidget(harness(seeded));
    expect(find.text('Day 1'), findsOneWidget);
    expect(find.text('Day 3'), findsOneWidget);
    expect(find.text('Jongno · Bukchon · Insadong'), findsOneWidget);
    expect(find.text('Hongdae · Sinchon · Mapo'), findsOneWidget);
    expect(find.text('Anything special this day? (optional)'), findsNWidgets(3));
  });

  testWidgets('a seven day trip shows seven rows', (tester) async {
    final week = List.generate(7, (i) => DaySpec(day: i + 1, region: 'jongno'));
    // Each row is a zone plus a note field; the list builds lazily, so give it
    // room for all seven instead of the default 800x600.
    tester.view.physicalSize = const Size(800, 1600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(harness(week));
    expect(find.textContaining('Day '), findsNWidgets(7));
  });

  testWidgets('submits the zones and notes the rows currently hold', (tester) async {
    List<DaySpec>? sent;
    await tester.pumpWidget(harness(seeded, onSubmit: (v) => sent = v));

    await tester.tap(find.byKey(const ValueKey('region-2')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Jamsil').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('note-2')), "mom's birthday");
    await tester.pumpAndSettle();

    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();

    expect(sent, isNotNull);
    expect(sent![1].region, 'jamsil');
    expect(sent![1].note, "mom's birthday");
    expect(sent![0].region, 'jongno');
    expect(sent![0].note, '');
  });
}
