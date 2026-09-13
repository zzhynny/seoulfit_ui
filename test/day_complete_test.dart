import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/data/mock/mock_trip_repository.dart';
import 'package:seoulfit_ui/providers/trip_provider.dart';
import 'package:seoulfit_ui/screens/trip/day_complete_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  // Check-in closes out the whole trip at once, so completing it from the
  // Day 2 tab used to read "5 of 5" when the trip had 15 stops.
  testWidgets('counts every stop on every day, not just one tab', (tester) async {
    final trip = TripProvider(MockTripRepository());
    await tester.runAsync(() => trip.generateItinerary());
    final days = trip.itinerary!.days;
    final total = days.fold(0, (sum, d) => sum + d.activities.length);
    final visited = days.fold(0, (sum, d) => sum + d.visitedCount);
    expect(days.last.activities.length, lessThan(total), reason: 'fixture needs 2+ days');

    await tester.pumpWidget(
      ChangeNotifierProvider<TripProvider>.value(
        value: trip,
        child: MaterialApp(
          home: Scaffold(body: DayCompleteScreen(onContinue: () {}, onBack: () {})),
        ),
      ),
    );

    expect(find.text('$visited of $total places visited'), findsOneWidget);
    expect(find.text('Check-in Complete'), findsOneWidget);
  });
}
