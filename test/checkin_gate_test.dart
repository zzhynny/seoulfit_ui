import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/data/mock/mock_trip_repository.dart';
import 'package:seoulfit_ui/models/trip.dart';
import 'package:seoulfit_ui/providers/companion_provider.dart';
import 'package:seoulfit_ui/providers/trip_provider.dart';
import 'package:seoulfit_ui/screens/trip/day_checkin_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  List<TripActivity> openOn(TripProvider trip, int day) => trip.itinerary!.days
      .firstWhere((d) => d.dayNumber == day)
      .activities
      .where((a) => !a.visited)
      .toList();

  test('open stops are counted on every day, not just the one on screen', () async {
    final trip = TripProvider(MockTripRepository());
    await trip.generateItinerary();
    final open = trip.openStopsByDay;
    expect(open.length, greaterThan(1), reason: 'fixture must leave stops open on 2+ days');

    final stop = openOn(trip, 1).first;
    trip.markMissed(stop.id, MissedReason.tooTired);
    expect(trip.openStopsByDay[1] ?? 0, open[1]! - 1);

    for (final a in openOn(trip, 1)) {
      trip.setVisited(a.id, true);
    }
    expect(trip.openStopsByDay.containsKey(1), isFalse);
  });

  test('checking a stop in clears the reason it was given', () async {
    // Otherwise the record says the stop was both visited and missed.
    final trip = TripProvider(MockTripRepository());
    await trip.generateItinerary();
    final stop = openOn(trip, 1).first;

    trip.markMissed(stop.id, MissedReason.tooTired);
    trip.setVisited(stop.id, true);

    expect(trip.reasonFor(stop.id), isNull);
  });

  testWidgets('Complete Check-in unlocks only once every day is settled',
      (tester) async {
    final trip = TripProvider(MockTripRepository());
    await tester.runAsync(() => trip.generateItinerary());
    tester.view.physicalSize = const Size(393, 852);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    var completed = 0;
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<TripProvider>.value(value: trip),
          ChangeNotifierProvider(create: (_) => CompanionProvider()),
        ],
        child: MaterialApp(
          home: Scaffold(
            body: DayCheckInScreen(
              dayNumber: 1,
              onComplete: () => completed++,
              onMissedPlace: (_) {},
              onBack: () {},
              onSelectDay: (_) {},
            ),
          ),
        ),
      ),
    );

    ElevatedButton button() =>
        tester.widget(find.widgetWithText(ElevatedButton, 'Complete Check-in'));

    expect(button().onPressed, isNull);

    // Settle Day 1 only: one skipped with a reason, the rest checked in.
    // Fake time, as trip_recap_test does -- real async gives google_fonts room
    // to try (and fail) a network font download mid-test.
    final day1 = openOn(trip, 1);
    trip.markMissed(day1.first.id, MissedReason.tooTired);
    for (final a in day1.skip(1)) {
      trip.setVisited(a.id, true);
    }
    await tester.pump();

    expect(find.textContaining('Too tired'), findsOneWidget);
    final otherDay = trip.openStopsByDay.keys.first;
    expect(button().onPressed, isNull, reason: 'Day $otherDay still has open stops');
    expect(find.textContaining('Day $otherDay: '), findsOneWidget);

    for (final day in trip.itinerary!.days) {
      for (final a in openOn(trip, day.dayNumber)) {
        if (trip.reasonFor(a.id) == null) trip.setVisited(a.id, true);
      }
    }
    await tester.pump();

    expect(find.textContaining('Still open'), findsNothing);
    expect(button().onPressed, isNotNull);

    await tester.tap(find.text('Complete Check-in'));
    await tester.pump();
    expect(completed, 1);
  });
}
