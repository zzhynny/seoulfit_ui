import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/data/mock/mock_trip_repository.dart';
import 'package:seoulfit_ui/models/trip.dart';
import 'package:seoulfit_ui/providers/trip_provider.dart';
import 'package:seoulfit_ui/screens/profile/trip_recap_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  // The stamp's own labels can be misspelled and skip unvisited places, so the
  // list under it is where every place is guaranteed to show up.
  testWidgets('lists every place by day, in order, with skip reasons',
      (tester) async {
    final trip = TripProvider(MockTripRepository());
    await tester.runAsync(() => trip.generateItinerary());
    final days = trip.itinerary!.days;
    final skipped = days.first.activities.firstWhere((a) => !a.visited);

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: RecapRouteList(
            days: days,
            reasonFor: (id) => id == skipped.id ? MissedReason.tooTired : null,
          ),
        ),
      ),
    ));

    for (final day in days) {
      expect(find.textContaining('Day ${day.dayNumber} ·'), findsOneWidget);
      for (var i = 0; i < day.activities.length; i++) {
        expect(find.text('${i + 1}. ${day.activities[i].title}'), findsWidgets);
      }
    }
    expect(find.text('Too tired'), findsOneWidget);
  });
}
