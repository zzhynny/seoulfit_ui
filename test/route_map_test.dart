import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/models/trip.dart';
import 'package:seoulfit_ui/widgets/route_map.dart';

TripActivity stop(String name, {double? lat, double? lng, bool included = true}) =>
    TripActivity(
      id: name,
      time: '9:00 AM',
      category: ActivityCategory.culture,
      title: name,
      description: '',
      lat: lat,
      lng: lng,
      included: included,
    );

Itinerary itineraryOf(List<List<TripActivity>> days) => Itinerary(
      preferences: const TripPreferences(
        dateRange: '', region: '', travelStyle: '',
        groupSize: '', dietaryNotes: '', pace: '',
      ),
      routeStops: const [],
      days: [
        for (var i = 0; i < days.length; i++)
          TripDay(dayNumber: i + 1, date: '', areaName: '', activities: days[i]),
      ],
    );

void main() {
  test('numbers stops continuously across days', () {
    final days = mappableDays(itineraryOf([
      [stop('A', lat: 37.57, lng: 126.97), stop('B', lat: 37.58, lng: 126.98)],
      [stop('C', lat: 37.55, lng: 126.92)],
    ]));

    expect(days, hasLength(2));
    expect(days[0].map((s) => s.order), [1, 2]);
    // Day 2 continues the count — the route list under the map is one
    // sequence, so restarting at 1 would disagree with it.
    expect(days[1].map((s) => s.order), [3]);
  });

  test('an ungeocoded stop leaves a gap rather than shifting later numbers',
      () {
    final days = mappableDays(itineraryOf([
      [
        stop('A', lat: 37.57, lng: 126.97),
        stop('No coords'),
        stop('C', lat: 37.58, lng: 126.98),
      ],
    ]));

    expect(days.single.map((s) => s.order), [1, 3]);
  });

  test('excluded stops are neither plotted nor counted', () {
    final days = mappableDays(itineraryOf([
      [
        stop('A', lat: 37.57, lng: 126.97),
        stop('Dropped', lat: 37.575, lng: 126.975, included: false),
        stop('C', lat: 37.58, lng: 126.98),
      ],
    ]));

    expect(days.single.map((s) => s.order), [1, 2]);
  });

  test('a day with nothing plottable is dropped entirely', () {
    final days = mappableDays(itineraryOf([
      [stop('A', lat: 37.57, lng: 126.97)],
      [stop('No coords')],
    ]));

    expect(days, hasLength(1));
  });

  testWidgets('falls back to the Figma illustration with no coordinates',
      (tester) async {
    // Every mock itinerary looks like this: display copy, no geography. The
    // fallback must not reach for a tile server.
    await tester.pumpWidget(MaterialApp(
      home: RouteMap(itinerary: itineraryOf([[stop('A'), stop('B')]])),
    ));

    expect(find.byType(Image), findsOneWidget);
  });
}
