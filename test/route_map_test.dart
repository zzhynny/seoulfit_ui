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

  test('an excluded stop is not plotted but still consumes its number', () {
    // The printed route list numbers every stop, switched off or not. Having
    // the map skip it from the count too renumbered everything after it, so
    // marker 2 pointed at row 3.
    final days = mappableDays(itineraryOf([
      [
        stop('A', lat: 37.57, lng: 126.97),
        stop('Dropped', lat: 37.575, lng: 126.975, included: false),
        stop('C', lat: 37.58, lng: 126.98),
      ],
    ]));

    expect(days.single.map((s) => s.order), [1, 3]);
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

  testWidgets('picks the map, not the illustration, once stops have coordinates',
      (tester) async {
    // Coordinates from a live generation against the webapp backend. The
    // reported symptom was the map "looking like an image", i.e. the Figma
    // fallback winning with real data — so this asserts the branch.
    //
    // Only the branch: whether flutter_map then paints its markers is its
    // concern, and asserting it here means faking an HttpClient for the tile
    // requests, which tests the fake more than the app.
    await tester.pumpWidget(MaterialApp(
      home: RouteMap(
        itinerary: itineraryOf([
          [
            stop('GangGang Sul Lai', lat: 37.5523988, lng: 126.9226),
            stop('Hongdae Food Street', lat: 37.5529929, lng: 126.9216827),
          ],
        ]),
      ),
    ));

    // The illustration is an Image.asset; the map branch renders none.
    expect(find.byType(Image), findsNothing);
    // The placeholder sits behind the tiles so an unpainted map never reads
    // as a broken image.
    expect(find.text('Loading map…'), findsOneWidget);

    // The tile layer really reaches for openstreetmap.org, which the test
    // binding answers with a 400. Those failures are the harness, not the
    // widget, and the app already renders them as the placeholder — drain
    // them so they don't fail the assertions above.
    while (tester.takeException() != null) {}
  });

  group('onlyDay', () {
    Itinerary threeDays() => itineraryOf([
          [stop('A', lat: 37.57, lng: 126.97), stop('B', lat: 37.58, lng: 126.98)],
          [stop('C', lat: 37.55, lng: 126.92)],
          [stop('D', lat: 37.50, lng: 127.03)],
        ]);

    test('filters the map to the day the tabs are showing', () {
      // The tabs filtered the stop list but every day stayed on the map, so
      // the two disagreed about what was selected.
      final days = mappableDays(threeDays(), onlyDay: 2);

      expect(days, hasLength(1));
      expect(days.single.single.dayNumber, 2);
    });

    test('markers keep their trip-wide numbers when filtered', () {
      // Day 2's stop is the third of the trip. Renumbering it 1 would
      // disagree with the route list printed under the map.
      expect(mappableDays(threeDays(), onlyDay: 2).single.single.order, 3);
      expect(mappableDays(threeDays(), onlyDay: 3).single.single.order, 4);
    });

    test('a skipped day consumes its numbers even with a stop switched off',
        () {
      final itinerary = itineraryOf([
        [
          stop('A', lat: 37.57, lng: 126.97),
          stop('Off', lat: 37.575, lng: 126.975, included: false),
        ],
        [stop('C', lat: 37.55, lng: 126.92)],
      ]);

      // Day 1 holds numbers 1 and 2 whether or not its second stop is on, so
      // day 2's stop is 3 either way.
      expect(mappableDays(itinerary, onlyDay: 2).single.single.order, 3);
      expect(mappableDays(itinerary).last.single.order, 3);
    });

    test('null shows the whole trip', () {
      expect(mappableDays(threeDays()), hasLength(3));
    });

    test('day number rides along so colours survive filtering', () {
      // Colour is keyed off the day number, not list position, so day 3 is
      // the same colour whether or not days 1 and 2 are on screen.
      final all = mappableDays(threeDays());
      expect(all.last.single.dayNumber, 3);
      expect(mappableDays(threeDays(), onlyDay: 3).single.single.dayNumber, 3);
    });
  });
}
