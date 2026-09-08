import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/data/mock/mock_trip_repository.dart';
import 'package:seoulfit_ui/models/trip.dart';
import 'package:seoulfit_ui/providers/trip_provider.dart';
import 'package:seoulfit_ui/screens/trip/final_route_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Two stops with a fully-populated hop between them, so every branch of the
/// transport UI is on screen at once.
Itinerary routed() {
  const hop = TransitHop(
    options: [
      TransitChoice(
        label: 'Subway',
        segments: ['Line 2', 'Line 3'],
        totalMinutes: 18,
        fareWon: 1400,
        transfers: 1,
        walkMeters: 220,
      ),
      TransitChoice(label: 'Bus', segments: ['Bus 273'], totalMinutes: 26),
    ],
    distanceKm: 4.2,
    walkMinutes: 52,
    carMinutes: 14,
    kakaoWalkUrl: 'https://m.map.kakao.com/scheme/route?by=foot',
    kakaoCarUrl: 'https://m.map.kakao.com/scheme/route?by=car',
    kakaoTransitUrl: 'https://m.map.kakao.com/scheme/route?by=publictransit',
  );

  const stops = [
    RouteStop(
      order: 1,
      nameEn: 'Gyeongbokgung',
      nameKo: '경복궁',
      arrivalTime: '9:30 AM',
      exitInstruction: 'Get off: Exit 5, walk 200m north',
      hop: hop,
    ),
    RouteStop(order: 2, nameEn: 'Bukchon Hanok Village', arrivalTime: '11:00 AM'),
  ];

  return Itinerary(
    preferences: const TripPreferences(
      dateRange: '', region: '', travelStyle: '',
      groupSize: '', dietaryNotes: '', pace: '',
    ),
    routeStops: stops,
    days: [
      TripDay(
        dayNumber: 1,
        date: 'Mar 3',
        areaName: 'Jongno',
        activities: [
          for (final s in stops)
            TripActivity(
              id: s.nameEn,
              time: s.arrivalTime,
              category: ActivityCategory.culture,
              title: s.nameEn,
              description: '',
            ),
        ],
      ),
    ],
  );
}

Future<void> pump(WidgetTester tester, Itinerary itinerary) async {
  tester.view.physicalSize = const Size(393, 852);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ChangeNotifierProvider<TripProvider>(
      create: (_) => TripProvider(MockTripRepository()),
      child: MaterialApp(
        home: Scaffold(
          body: FinalRouteScreen(
            itinerary: itinerary,
            onResetItinerary: () {},
            onBack: () {},
          ),
        ),
      ),
    ),
  );
  await tester.pump();
  while (tester.takeException() != null) {}
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('every transport chip on screen is actually tappable',
      (tester) async {
    // The subway and bus chips were built without an onTap at all, while the
    // walk and drive chips beside them opened Kakao -- same size, same shape,
    // half of them dead. This asserts the whole row, so a future chip added
    // without a tap target fails here rather than in someone's hand.
    await pump(tester, routed());

    final chips = find.byType(TransportChip);
    expect(chips, findsWidgets);
    for (final chip in tester.widgetList<TransportChip>(chips)) {
      expect(chip.onTap, isNotNull, reason: '"${chip.label}" is not tappable');
    }
  });

  testWidgets('the arrival hint expands to the planner instruction',
      (tester) async {
    // exitInstruction was parsed, modelled and then never rendered: the
    // "How do I know I'm here?" row carried a chevron and no handler.
    await pump(tester, routed());

    expect(find.text('Get off: Exit 5, walk 200m north'), findsNothing);

    await tester.tap(find.textContaining("How do I know I'm here?"));
    await tester.pumpAndSettle();

    expect(find.text('Get off: Exit 5, walk 200m north'), findsOneWidget);
  });

  testWidgets('a stop with no arrival instruction offers no expander',
      (tester) async {
    // Bukchon has no exitInstruction, so the affordance must not be there at
    // all -- an expander that opens onto nothing is the same bug again.
    await pump(tester, routed());

    expect(find.textContaining("How do I know I'm here?"), findsOneWidget);
  });

  testWidgets('the leading option is marked as the recommended one',
      (tester) async {
    await pump(tester, routed());

    final chips = tester.widgetList<TransportChip>(find.byType(TransportChip));
    expect(chips.where((c) => c.primary), hasLength(1));
    expect(chips.first.primary, isTrue);
    expect(chips.first.label, contains('Subway'));
  });

  testWidgets('fare, transfers and walk are separate facts, not one string',
      (tester) async {
    // _detailLine joined everything with a middle dot into a single run of
    // text that read as noise. Each fact gets its own label.
    await pump(tester, routed());

    expect(find.text('Line 2 → Line 3'), findsOneWidget);
    expect(find.text('1 transfer'), findsOneWidget);
    expect(find.text('₩1,400'), findsOneWidget);
    expect(find.text('220m walk'), findsOneWidget);
  });
}
