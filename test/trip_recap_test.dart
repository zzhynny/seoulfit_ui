import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/data/mock/mock_trip_repository.dart';
import 'package:seoulfit_ui/providers/trip_provider.dart';
import 'package:seoulfit_ui/screens/profile/trip_recap_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> pump(WidgetTester tester, TripProvider provider) async {
    tester.view.physicalSize = const Size(375, 812);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      ChangeNotifierProvider<TripProvider>.value(
        value: provider,
        child: MaterialApp(
          home: Scaffold(
            body: TripRecapScreen(onDone: () {}, onBack: () {}),
          ),
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 400));
  }

  // Both variants used to overflow their row on a 375pt phone — a
  // yellow-and-black stripe across the stamp book / railway card.
  testWidgets('low-data recap lays out on a 375pt phone', (tester) async {
    await pump(tester, TripProvider(MockTripRepository()));
    expect(tester.takeException(), isNull);
  });

  testWidgets('full railway recap lays out on a 375pt phone', (tester) async {
    final p = TripProvider(MockTripRepository());
    await tester.runAsync(() => p.generateItinerary());
    expect(p.itinerary!.stampedDays, greaterThanOrEqualTo(kFullRecapStampThreshold));
    await pump(tester, p);
    expect(tester.takeException(), isNull);
  });

  // Which body renders is decided purely by how many days carry a check-in.
  // That made the day-tab bug in DayCheckInScreen -- which pinned the
  // traveller to Day 1 -- surface here as "the railway illustration never
  // appears", with nothing wrong in this file at all. These pin the
  // threshold so that link stays visible if either side moves again.
  Future<TripProvider> stampedOn(WidgetTester tester, int dayCount) async {
    final p = TripProvider(MockTripRepository());
    await tester.runAsync(() => p.generateItinerary());
    for (final day in p.itinerary!.days) {
      for (final a in day.activities) {
        p.setVisited(a.id, day.dayNumber <= dayCount);
      }
    }
    return p;
  }

  testWidgets('one stamped day is below the railway threshold', (tester) async {
    final p = await stampedOn(tester, 1);
    expect(p.itinerary!.stampedDays, 1);
    await pump(tester, p);

    expect(find.text('YOUR STAMP BOOK'), findsOneWidget);
    expect(
      find.image(const AssetImage('assets/images/recap-railway-bg.png')),
      findsNothing,
    );
  });

  testWidgets('a second stamped day brings up the railway map', (tester) async {
    final p = await stampedOn(tester, 2);
    expect(p.itinerary!.stampedDays, 2);
    await pump(tester, p);

    expect(
      find.image(const AssetImage('assets/images/recap-railway-bg.png')),
      findsOneWidget,
    );
  });
}
