import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/data/mock/mock_trip_repository.dart';
import 'package:seoulfit_ui/providers/companion_provider.dart';
import 'package:seoulfit_ui/providers/trip_provider.dart';
import 'package:seoulfit_ui/screens/trip/day_checkin_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> pumpAt(
    WidgetTester tester,
    Size size, {
    required TripProvider trip,
    required ValueChanged<int> onSelectDay,
    int dayNumber = 1,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<TripProvider>.value(value: trip),
          ChangeNotifierProvider(create: (_) => CompanionProvider()),
        ],
        child: MaterialApp(
          home: Scaffold(
            body: DayCheckInScreen(
              dayNumber: dayNumber,
              onComplete: () {},
              onMissedPlace: (_) {},
              onBack: () {},
              onSelectDay: onSelectDay,
            ),
          ),
        ),
      ),
    );
  }

  // The header row laid a 30px avatar, "Day N Check-in" at 24pt and the
  // stamped-days chip side by side with only the middle one flexible, so it
  // overflowed by 269px on an iPhone 17 and 287px on a 375pt phone -- a
  // yellow-and-black stripe across the top of every check-in.
  for (final size in const [Size(375, 812), Size(393, 852), Size(320, 568)]) {
    testWidgets('the header fits a ${size.width.toInt()}pt phone',
        (tester) async {
      final trip = TripProvider(MockTripRepository());
      await tester.runAsync(() => trip.generateItinerary());
      await pumpAt(tester, size, trip: trip, onSelectDay: (_) {});

      expect(tester.takeException(), isNull);
    });
  }

  // The day tabs sat above the check-in list with an empty onSelect, so
  // tapping Day 2 did nothing at all. The screen is only ever entered at
  // /day-checkin/1, which left every day but the first unreachable -- and,
  // downstream, capped stampedDays at 1 so the trip recap could never clear
  // its 2-day threshold for the railway map.
  testWidgets('tapping a day tab asks to switch days', (tester) async {
    final trip = TripProvider(MockTripRepository());
    await tester.runAsync(() => trip.generateItinerary());
    final days = trip.itinerary!.days;
    expect(days.length, greaterThan(1), reason: 'need a Day 2 to tap');

    final selected = <int>[];
    await pumpAt(tester, const Size(393, 852),
        trip: trip, onSelectDay: selected.add);

    await tester.tap(find.text('Day 2'));
    await tester.pump();

    expect(selected, [2]);
    expect(tester.takeException(), isNull);
  });

  testWidgets('the day it is already showing is still reported', (tester) async {
    // Re-tapping the current day must not be swallowed either -- the router
    // decides what a same-day tap means, not the screen.
    final trip = TripProvider(MockTripRepository());
    await tester.runAsync(() => trip.generateItinerary());

    final selected = <int>[];
    await pumpAt(tester, const Size(393, 852),
        trip: trip, onSelectDay: selected.add);

    await tester.tap(find.text('Day 1'));
    await tester.pump();

    expect(selected, [1]);
    expect(tester.takeException(), isNull);
  });
}
