import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
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

  testWidgets('the zoom buttons actually move the camera', (tester) async {
    // The +/- buttons exist because the map is only 128-200px tall inside a
    // scrolling list. They were inert: RouteMap held a MapController that was
    // never handed to FlutterMap, so flutter_map built its own and every
    // _zoomBy() read of `_controller.camera` threw
    // "You need to have the FlutterMap widget rendered at least once".
    //
    // Read the camera the way a layer does, through the inherited
    // MapCamera -- that is the camera the map actually paints, so it can't
    // agree with a controller the map isn't listening to.
    await tester.pumpWidget(MaterialApp(
      home: RouteMap(
        itinerary: itineraryOf([
          [
            // Far enough apart that initialCameraFit lands well below
            // maxZoom -- two stops on one street fit at 18 and "zoom in"
            // is then correctly a no-op, which would pass for the bug.
            stop('Hongdae', lat: 37.5523988, lng: 126.9226),
            stop('Gangnam', lat: 37.4979, lng: 127.0276),
          ],
        ]),
      ),
    ));
    // Tile requests 400 against the test binding. Those are the harness, not
    // the widget, so they get drained after every pump -- the assertion that
    // matters is whether the painted camera moved, which is exactly what an
    // unbound controller cannot do.
    while (tester.takeException() != null) {}

    double zoom() => MapCamera.of(tester.element(find.byType(MarkerLayer))).zoom;

    // initialCameraFit is applied during the map's first layout, so the very
    // first frame still reports the pre-fit zoom. Let it settle before
    // sampling, or the fit's own jump reads as the button working.
    await tester.pump();
    while (tester.takeException() != null) {}
    final before = zoom();

    await tester.tap(find.byTooltip('Zoom in'));
    await tester.pump();
    while (tester.takeException() != null) {}
    expect(zoom(), greaterThan(before));

    await tester.tap(find.byTooltip('Zoom out'));
    await tester.pump();
    while (tester.takeException() != null) {}
    expect(zoom(), closeTo(before, 0.001));
  });

  testWidgets('a stop is no longer buried under a later one standing beside it',
      (tester) async {
    // Reported as "the first stop of the day isn't plotted". It was plotted:
    // MarkerLayer paints in list order, so stop 1 sat under every later stop,
    // and at the zoom a day fits into a phone-sized map a 28px marker spans
    // ~185m. Two stops 60m apart drew 9px apart and stop 2 covered stop 1.
    //
    // Sized like a phone on purpose: under the test binding's tight 800x600 the
    // SizedBox(height: 192) is ignored, the fit lands 2 zoom levels in, and the
    // markers separate on their own.
    const hongdae = LatLng(37.5524, 126.9226);
    await tester.pumpWidget(MaterialApp(
      home: Center(
        child: SizedBox(
          width: 360,
          height: 192,
          child: RouteMap(
            height: 192,
            itinerary: itineraryOf([
              [
                stop('Hongdae', lat: hongdae.latitude, lng: hongdae.longitude),
                // ~60m north: a restaurant across the street from stop 1.
                stop('Meal', lat: 37.55294, lng: 126.9226),
                // Far enough off to set a neighbourhood-scale camera fit.
                stop('Yeonnam', lat: 37.5600, lng: 126.9300),
              ],
            ]),
          ),
        ),
      ),
    ));
    await tester.pump();
    while (tester.takeException() != null) {}

    Rect marker(String number) => tester.getRect(
        find.ancestor(of: find.text(number), matching: find.byType(Container)).first);

    expect(marker('1').overlaps(marker('2')), isFalse);

    // Stop 1 is the one that keeps its true position; the later stop moves.
    final markers = tester.widget<MarkerLayer>(find.byType(MarkerLayer)).markers;
    expect(markers.first.point.latitude, closeTo(hongdae.latitude, 1e-9));
    expect(markers.first.point.longitude, closeTo(hongdae.longitude, 1e-9));
  });

  group('spreadMarkers', () {
    test('leaves markers that do not touch where they are', () {
      const points = [Offset(0, 0), Offset(100, 0)];
      expect(spreadMarkers(points), points);
    });

    test('moves a later marker off an earlier one, by as little as it can', () {
      final spots = spreadMarkers(const [Offset(0, 0), Offset(0, 9)]);
      expect(spots.first, Offset.zero);
      expect((spots[1] - spots[0]).distance, greaterThanOrEqualTo(28));
      // One ring out from its own point, not flung across the map.
      expect((spots[1] - const Offset(0, 9)).distance, closeTo(28, 1e-9));
    });

    test('a pile of markers on one spot all end up clear of each other', () {
      final spots = spreadMarkers(List.filled(12, Offset.zero));
      for (var i = 0; i < spots.length; i++) {
        for (var j = i + 1; j < spots.length; j++) {
          expect((spots[i] - spots[j]).distance, greaterThanOrEqualTo(28 - 1e-9),
              reason: 'markers $i and $j overlap');
        }
      }
    });
  });

  testWidgets('switching days recentres the map on that day', (tester) async {
    // The day tabs already filtered which markers were drawn, but the camera
    // stayed on the fit computed for whatever day was showing first, so
    // picking day 2 left its stops off-screen -- an empty-looking map.
    final trip = itineraryOf([
      [stop('Hongdae', lat: 37.5524, lng: 126.9226)],
      [stop('Gangnam', lat: 37.4979, lng: 127.0276)],
    ]);

    Future<void> show(int day) async {
      await tester.pumpWidget(MaterialApp(
        home: RouteMap(itinerary: trip, onlyDay: day),
      ));
      await tester.pump();
      while (tester.takeException() != null) {}
    }

    LatLng centre() =>
        MapCamera.of(tester.element(find.byType(MarkerLayer))).center;

    await show(1);
    final onDayOne = centre();
    expect(onDayOne.latitude, closeTo(37.5524, 0.01));

    await show(2);
    final onDayTwo = centre();
    expect(onDayTwo.latitude, closeTo(37.4979, 0.01));
    expect(onDayTwo.longitude, closeTo(127.0276, 0.01));
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
