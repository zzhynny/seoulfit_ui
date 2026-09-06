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
      region: '  ',
    ));

    expect(prefs.dateRange, 'Oct 12 for 5 days');
    expect(prefs.region, '—');
    expect(prefs.pace, '—');
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
      const api.TravelState(travelDates: 'October 12-14', region: 'Jongno'),
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

    // Route stops flatten in visit order and carry the leg detail.
    expect(itinerary.routeStops.map((s) => s.order), [1, 2, 3]);
    expect(itinerary.routeStops.first.transitDetail, '0.1 km · 1 min walk');
    expect(itinerary.preferences.dateRange, 'October 12-14');
  });
}
