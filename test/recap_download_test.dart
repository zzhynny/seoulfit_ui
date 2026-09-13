import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/data/mock/mock_trip_repository.dart';
import 'package:seoulfit_ui/providers/trip_provider.dart';
import 'package:seoulfit_ui/screens/profile/trip_recap_screen.dart';
import 'package:seoulfit_ui/services/api_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  final download = find.text('Download');

  // Two fully stamped days: enough for the full railway recap, and checking in
  // mints the trip id the stamp is stored under.
  Future<TripProvider> finishedTrip(WidgetTester tester) async {
    final trip = TripProvider(MockTripRepository());
    await tester.runAsync(() => trip.generateItinerary());
    for (final day in trip.itinerary!.days) {
      for (final a in day.activities) {
        trip.setVisited(a.id, day.dayNumber <= 2);
      }
    }
    return trip;
  }

  Future<void> pumpRecap(
    WidgetTester tester,
    TripProvider trip, {
    required StampStatus status,
    Future<void> Function(String url)? saveStamp,
  }) async {
    tester.view.physicalSize = const Size(393, 852);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      ChangeNotifierProvider<TripProvider>.value(
        value: trip,
        child: MaterialApp(
          home: Scaffold(
            body: TripRecapScreen(
              onDone: () {},
              onBack: () {},
              fetchStampStatus: (_) async => status,
              saveStamp: saveStamp ?? (_) async {},
            ),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
    // Lets the railway card's delayed (180 ms) paw-stamp animation start, as
    // trip_recap_test does, so no timer outlives the test.
    await tester.pump(const Duration(milliseconds: 400));
  }

  testWidgets('the story card link is gone', (tester) async {
    final trip = await finishedTrip(tester);
    await pumpRecap(tester, trip, status: (status: 'ready', version: 42));

    expect(find.text('View as a story card'), findsNothing);
  });

  testWidgets('no Download button while the stamp is still being made',
      (tester) async {
    final trip = await finishedTrip(tester);
    await pumpRecap(tester, trip, status: (status: 'generating', version: null));

    expect(download, findsNothing);
  });

  testWidgets('Download saves the finished stamp and says so', (tester) async {
    final trip = await finishedTrip(tester);
    final saved = <String>[];
    await pumpRecap(
      tester,
      trip,
      status: (status: 'ready', version: 42),
      saveStamp: (url) async => saved.add(url),
    );

    expect(download, findsOneWidget);
    await tester.tap(download);
    await tester.pump();
    await tester.pump();

    expect(saved, hasLength(1));
    expect(saved.single, endsWith('/static/stamps/${trip.tripId}.png?v=42'));
    expect(find.text('Saved to Photos'), findsOneWidget);
    await tester.pump(const Duration(seconds: 5)); // let the message's hide timer run out
  });

  testWidgets('a failed save tells the traveller', (tester) async {
    final trip = await finishedTrip(tester);
    await pumpRecap(
      tester,
      trip,
      status: (status: 'ready', version: 42),
      saveStamp: (_) async => throw Exception('photo access denied'),
    );

    await tester.tap(download);
    await tester.pump();
    await tester.pump();

    expect(find.textContaining("Couldn't save"), findsOneWidget);
    await tester.pump(const Duration(seconds: 5)); // let the message's hide timer run out
  });
}
