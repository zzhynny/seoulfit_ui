import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/data/api/mappers.dart';
import 'package:seoulfit_ui/models/travel_state.dart' as api;
import 'package:seoulfit_ui/models/trip.dart';

/// Fixtures shaped like the backend's `as_output_poi` payload.
api.Poi poi(String name, {String type = 'tourist_spot', int stay = 60}) =>
    api.Poi(
      name: name,
      type: type,
      address: '$name, Jongno-gu',
      stayMinutes: stay,
      notes: '',
      lat: 37.5,
      lng: 127.0,
    );

void main() {
  group('categoryForPoiType', () {
    test('maps the planner vocabulary onto the UI enum', () {
      expect(categoryForPoiType('restaurant'), ActivityCategory.food);
      expect(categoryForPoiType('cafe'), ActivityCategory.teaHouse);
      expect(categoryForPoiType('shopping_mall'), ActivityCategory.shopping);
      expect(categoryForPoiType('market'), ActivityCategory.shopping);
      expect(categoryForPoiType('park'), ActivityCategory.nature);
      expect(categoryForPoiType('nature'), ActivityCategory.nature);
    });

    test('falls back to culture for the planner default and for junk', () {
      expect(categoryForPoiType('tourist_spot'), ActivityCategory.culture);
      expect(categoryForPoiType('museum'), ActivityCategory.culture);
      expect(categoryForPoiType(''), ActivityCategory.culture);
      expect(categoryForPoiType('  RESTAURANT '), ActivityCategory.food);
    });
  });

  group('clockLabel', () {
    test('counts from a 09:00 day start and crosses noon correctly', () {
      expect(clockLabel(0), '9:00 AM');
      expect(clockLabel(90), '10:30 AM');
      expect(clockLabel(180), '12:00 PM');
      expect(clockLabel(240), '1:00 PM');
    });
  });

  group('toUiDay', () {
    test('accumulates stay plus the leg that follows each stop', () {
      final day = api.ItineraryDay(
        day: 1,
        theme: 'Palaces',
        estimatedCost: '',
        pois: [poi('Gyeongbokgung', stay: 90), poi('Bukchon', stay: 60)],
        transitLegs: const [api.TransitLeg(walkMinutes: 15)],
      );

      final mapped = toUiDay(day);

      expect(mapped.dayNumber, 1);
      expect(mapped.areaName, 'Palaces');
      expect(mapped.activities.first.time, '9:00 AM');
      // 09:00 + 90 min stay + 15 min walk.
      expect(mapped.activities[1].time, '10:45 AM');
    });

    test('substitutes defaults when the planner set no stay or leg', () {
      final day = api.ItineraryDay(
        day: 2,
        theme: '',
        estimatedCost: '',
        pois: [poi('A', stay: 0), poi('B')],
      );

      // 09:00 + 60 default stay + 20 default hop.
      expect(toUiDay(day).activities[1].time, '10:20 AM');
    });
  });

  test('activity id is the POI name, which is what /revalidate matches on',
      () {
    final mapped = toUiActivity(poi('Gwangjang Market', type: 'market'), '9:00 AM');

    expect(mapped.id, 'Gwangjang Market');
    expect(mapped.title, 'Gwangjang Market');
    expect(mapped.category, ActivityCategory.shopping);
    expect(mapped.lat, 37.5);
    // No notes on the fixture, so the address stands in.
    expect(mapped.description, 'Gwangjang Market, Jongno-gu');
  });

  test('excludedIdsOf returns only the switched-off stops, by name', () {
    final itinerary = Itinerary(
      preferences: toUiPreferences(const api.TravelState()),
      routeStops: const [],
      days: [
        TripDay(
          dayNumber: 1,
          date: '',
          areaName: '',
          activities: [
            toUiActivity(poi('Keep'), '9:00 AM'),
            toUiActivity(poi('Drop'), '11:00 AM').copyWith(included: false),
          ],
        ),
      ],
    );

    expect(excludedIdsOf(itinerary), ['Drop']);
  });

  test('unanswered slots render as an em dash, not an empty row', () {
    final prefs = toUiPreferences(const api.TravelState(
      travelDates: 'Oct 12 for 5 days',
    ));

    expect(prefs.dateRange, 'Oct 12 for 5 days');
    expect(prefs.region, '—');
    expect(prefs.pace, '—');
  });

  test('Travel Style sums up the interests picked per day', () {
    // The chat no longer asks a trip-wide interest, so the Day Planner's
    // per-day picks are the only source left -- same as the Region row.
    final prefs = toUiPreferences(const api.TravelState(
      daySpecs: [
        api.DaySpec(day: 1, region: 'hongdae', interest: 'Food & Cafes'),
        api.DaySpec(day: 2, region: 'seongsu', interest: 'Shopping'),
        api.DaySpec(day: 3, region: 'jongno', interest: 'Food & Cafes'),
      ],
    ));

    expect(prefs.travelStyle, 'Food & Cafes, Shopping');
  });

  test('parses a real /chat itinerary payload end to end', () {
    // Trimmed verbatim from a live generation against the FastAPI backend —
    // same keys, same value shapes, real coordinates and legs.
    final payload = <String, dynamic>{
      'summary': 'Jongno and Hongdae over three days',
      'days': [
        {
          'day': 1,
          'theme': "Jongno's Royal Heritage and Traditional Flavors",
          'estimated_cost': '60,000 - 80,000 KRW (approx. \$45-\$60 USD)',
          'pois': [
            {
              'name': 'Gyeongbokgung Palace (경복궁)',
              'type': 'history',
              'address': '161 Sajik-ro, Jongno-gu',
              'area': 'jongno',
              'lat': 37.57755982674375,
              'lng': 126.97696722252101,
              'stay_minutes': 120,
              'notes': 'Seoul’s main royal palace.',
            },
            {
              'name': 'Bukchon Hanok Village (북촌한옥마을)',
              'type': 'tourist_spot',
              'address': '37 Gyedong-gil, Jongno-gu',
              'area': 'jongno',
              'lat': 37.579018508290275,
              'lng': 126.98505948636013,
              'stay_minutes': 90,
              'notes': '',
            },
            {
              'name': 'Osulloc Tea House – Bukchon',
              'type': 'cafe',
              'address': '19 Bukchon-ro, Jongno-gu',
              'area': 'jongno',
              'lat': 37.58104676298559,
              'lng': 126.98457155183145,
              'stay_minutes': 45,
              'notes': 'Green tea and desserts.',
            },
          ],
          'transit_legs': [
            {
              'from_idx': 0,
              'to_idx': 1,
              'distance_km': 0.09,
              'walk_minutes': 1,
              'car_minutes': 1,
              'transit_options': <dynamic>[],
            },
            {
              'from_idx': 1,
              'to_idx': 2,
              'distance_km': 0.21,
              'walk_minutes': 3,
              'car_minutes': 1,
              'transit_options': <dynamic>[],
            },
          ],
        },
      ],
      'sources': <dynamic>[],
    };

    final itinerary = toUiItinerary(
      api.Itinerary.fromJson(payload),
      const api.TravelState(travelDates: 'October 12-14'),
    );

    expect(itinerary.days, hasLength(1));
    final day = itinerary.days.single;
    expect(day.areaName, "Jongno's Royal Heritage and Traditional Flavors");
    expect(day.activities.map((a) => a.category), [
      ActivityCategory.culture, // history -> the catch-all
      ActivityCategory.culture, // tourist_spot -> the catch-all
      ActivityCategory.teaHouse, // cafe
    ]);

    // 09:00, +120 stay +1 walk, +90 stay +3 walk.
    expect(day.activities.map((a) => a.time),
        ['9:00 AM', '11:01 AM', '12:34 PM']);

    // Coordinates survive for the Final Route map.
    expect(day.activities.first.lat, closeTo(37.5775, 0.001));

    // Route stops flatten in visit order and carry the real leg.
    expect(itinerary.routeStops.map((s) => s.order), [1, 2, 3]);
    final hop = itinerary.routeStops.first.hop!;
    expect(hop.walkMinutes, 1);
    expect(hop.distanceKm, 0.09);
    // These stops are a block apart, so the backend skipped ODsay entirely.
    // An empty option list is normal, not a failure — a spent daily quota
    // (HTTP 429) produces exactly the same thing.
    expect(hop.options, isEmpty);
    expect(hop.hasAnything, isTrue);

    // The last stop of a day has nothing after it to route to.
    expect(itinerary.routeStops.last.hop, isNull);
    expect(itinerary.preferences.dateRange, 'October 12-14');
  });

  test('carries ODsay options through when the backend has them', () {
    // Shape from models/travel_state.dart's TransitOption, which mirrors the
    // backend's ODsay extraction. Quota was spent while this was built, so
    // the fixture stands in for a leg that did get options.
    final leg = api.TransitLeg.fromJson(const {
      'distance_km': 9.92,
      'walk_minutes': 149,
      'car_minutes': 20,
      'kakao_walk_url': 'https://m.map.kakao.com/scheme/route?by=foot',
      'transit_options': [
        {
          'type': 1,
          'type_label': 'Subway',
          'total_minutes': 34,
          'fare_won': 1500,
          'walk_meters': 610,
          'transfers': 1,
          'segments': ['Line 3', 'Line 2'],
        },
      ],
    });

    final hop = toUiHop(leg);

    expect(hop.options, hasLength(1));
    expect(hop.options.single.label, 'Subway');
    expect(hop.options.single.isSubway, isTrue);
    expect(hop.options.single.segments, ['Line 3', 'Line 2']);
    expect(hop.options.single.fareWon, 1500);
    expect(hop.walkMinutes, 149);
  });

  test('an unlabelled option still gets a usable chip label', () {
    final leg = api.TransitLeg.fromJson(const {
      'transit_options': [
        {'total_minutes': 12, 'segments': <String>[]},
      ],
    });

    expect(toUiHop(leg).options.single.label, 'Transit');
  });

  test('carries summary, sources, cost and critic scores off the payload', () {
    // These five all reached the mapper and were dropped on the floor, which
    // is why the itinerary screens showed less than the Flutter app's.
    final payload = <String, dynamic>{
      'summary': 'Three days across Jongno and Hongdae.',
      'critic_report': {
        'after': {'overall_score': 0.87, 'feasibility_score': 0.94},
      },
      'sources': [
        {
          'course_id': 'c-1',
          'course_title': 'Seoul Palace Walking Course',
          'source': 'Visit Seoul',
          'source_url': 'https://english.visitseoul.net/',
        },
      ],
      'days': [
        {
          'day': 1,
          'theme': 'Palaces',
          'estimated_cost': '60,000 - 80,000 KRW',
          'pois': [
            {'name': 'Gyeongbokgung', 'type': 'history', 'stay_minutes': 120},
          ],
        },
      ],
    };

    final itinerary = toUiItinerary(
      api.Itinerary.fromJson(payload),
      const api.TravelState(),
    );

    expect(itinerary.summary, 'Three days across Jongno and Hongdae.');
    expect(itinerary.overallScore, 0.87);
    expect(itinerary.feasibilityScore, 0.94);
    expect(itinerary.sources.single.courseTitle, 'Seoul Palace Walking Course');
    expect(itinerary.sources.single.source, 'Visit Seoul');
    expect(itinerary.days.single.estimatedCost, '60,000 - 80,000 KRW');
    // raw is kept verbatim so an export carries what the typed models drop.
    expect(itinerary.raw['critic_report'], isNotNull);
  });

  test('an unscored plan reports null rather than zero', () {
    final itinerary = toUiItinerary(
      api.Itinerary.fromJson(const {'days': []}),
      const api.TravelState(),
    );

    // A reassuring-looking 0.0 would read as "scored, and terrible".
    expect(itinerary.overallScore, isNull);
    expect(itinerary.feasibilityScore, isNull);
    expect(itinerary.summary, '');
    expect(itinerary.sources, isEmpty);
  });

  test('legs carry the pair they connect', () {
    // Needed the moment a recomputed /transit-legs list is used: that one is
    // flat across the whole selection, so a leg has to be matched to its
    // (from, to) pair by name rather than by position.
    final leg = api.TransitLeg.fromJson(const {
      'from_name': 'Gyeongbokgung',
      'to_name': 'Bukchon Hanok Village',
      'walk_minutes': 12,
    });

    expect(leg.fromName, 'Gyeongbokgung');
    expect(leg.toName, 'Bukchon Hanok Village');
  });

  test('a day pairs each leg with the stop it leaves from', () {
    // Verified against a live payload: every day carries exactly
    // len(pois) - 1 legs with sequential from_idx, so position is exact
    // here. This pins that assumption.
    final day = api.ItineraryDay.fromJson(const {
      'day': 1,
      'theme': '',
      'pois': [
        {'name': 'A', 'stay_minutes': 60},
        {'name': 'B', 'stay_minutes': 60},
        {'name': 'C', 'stay_minutes': 60},
      ],
      'transit_legs': [
        {'from_name': 'A', 'to_name': 'B', 'walk_minutes': 5},
        {'from_name': 'B', 'to_name': 'C', 'walk_minutes': 9},
      ],
    });

    expect(day.transitLegs.length, day.pois.length - 1);
    for (var i = 0; i < day.transitLegs.length; i++) {
      expect(day.transitLegs[i].fromName, day.pois[i].name);
      expect(day.transitLegs[i].toName, day.pois[i + 1].name);
    }
  });
}
