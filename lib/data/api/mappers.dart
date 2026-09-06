/// Converts the FastAPI backend's payloads (`models/travel_state.dart`) into
/// the UI's own trip models (`models/trip.dart`).
///
/// Both files declare an `Itinerary`, so the backend one is always aliased
/// `api.` here. This is the only file that should need to know both shapes —
/// screens see UI models exclusively.
library;

import '../../models/travel_state.dart' as api;
import '../../models/trip.dart';

/// Fallback stay when the planner didn't set one. Mirrors the same default in
/// the app's route screen, so arrival clock times agree between the two.
const _defaultStayMinutes = 60;

/// Fallback hop between consecutive stops when a day has no transit leg for
/// the pair (the planner omits legs it couldn't route).
const _defaultTravelMinutes = 20;

/// Every itinerary day is planned as starting at 09:00.
const _dayStartMinutes = 9 * 60;

/// The planner writes `poi_type` as loose free text — `tourist_spot`,
/// `restaurant`, `cafe`, `shopping`, `shopping_mall`, `market`, `museum`,
/// `park`, `palace`, `history`, `nature` — with `tourist_spot` as its own
/// fallback. Anything unrecognised lands on [ActivityCategory.culture], which
/// is both the most common real value and the neutral tag colour.
///
/// [ActivityCategory.crafts] is unreachable from backend data: no POI type
/// maps to it. It stays in the enum for the mock repository's Figma-parity
/// data.
ActivityCategory categoryForPoiType(String type) {
  switch (type.toLowerCase().trim()) {
    case 'restaurant':
      return ActivityCategory.food;
    case 'cafe':
      return ActivityCategory.teaHouse;
    case 'shopping':
    case 'shopping_mall':
    case 'market':
      return ActivityCategory.shopping;
    case 'park':
    case 'nature':
      return ActivityCategory.nature;
    default:
      return ActivityCategory.culture;
  }
}

/// Formats minutes-since-09:00 as a 12-hour clock label.
String clockLabel(int minutesFromDayStart) {
  final total = _dayStartMinutes + minutesFromDayStart;
  var hour = (total ~/ 60) % 24;
  final minute = total % 60;
  final meridiem = hour >= 12 ? 'PM' : 'AM';
  hour = hour % 12;
  if (hour == 0) hour = 12;
  return '$hour:${minute.toString().padLeft(2, '0')} $meridiem';
}

/// Minutes to get from stop [index] to the next one, read off the day's
/// transit legs (one leg per consecutive pair). Walking wins when both are
/// known: these are neighbourhood-scale hops and the planner groups a day
/// into one area.
///
/// A missing leg and a missing *next stop* are different cases. The planner
/// omits legs it couldn't route, and treating that as a zero-minute hop
/// stacks the whole day at 9:00 AM; only the final stop of a day genuinely
/// has nothing following it.
int travelMinutesAfter(List<api.TransitLeg> legs, int index, int stopCount) {
  if (index >= stopCount - 1) return 0;
  if (index >= legs.length) return _defaultTravelMinutes;
  final leg = legs[index];
  return leg.walkMinutes ?? leg.carMinutes ?? _defaultTravelMinutes;
}

TripActivity toUiActivity(api.Poi poi, String time) {
  return TripActivity(
    // The backend has no stable POI id — `apply_slot_edits` matches purely on
    // `normalize_text(name)`, and `as_output_poi` emits no id field at all.
    // So the name IS the id: anything else breaks exclusion and swap
    // round-tripping through POST /revalidate.
    id: poi.name,
    time: time,
    category: categoryForPoiType(poi.type),
    title: poi.name,
    // `notes` is the planner's one-line pitch for the stop; the address is a
    // duller but non-empty stand-in when it didn't write one.
    description: poi.notes.isNotEmpty ? poi.notes : poi.address,
    lat: poi.lat,
    lng: poi.lng,
    poiType: poi.type,
  );
}

TripDay toUiDay(api.ItineraryDay day) {
  final activities = <TripActivity>[];
  var offset = 0;

  for (var i = 0; i < day.pois.length; i++) {
    final poi = day.pois[i];
    activities.add(toUiActivity(poi, clockLabel(offset)));
    final stay = poi.stayMinutes > 0 ? poi.stayMinutes : _defaultStayMinutes;
    offset += stay + travelMinutesAfter(day.transitLegs, i, day.pois.length);
  }

  return TripDay(
    dayNumber: day.day,
    // ponytail: no per-day calendar date. The graph parses one into
    // `trip_start_date` (graph.py) and `date_utils.date_for_day` can format
    // it, but `StateResponse` never sends it to the client, and
    // `travel_dates` is stored in the user's own free-text phrasing so it
    // can't be parsed here. Add `trip_start_date` to StateResponse and this
    // becomes a real date.
    date: '',
    areaName: day.theme,
    activities: activities,
    estimatedCost: day.estimatedCost,
  );
}

/// Flattens every day's stops into the single ordered list Final Route walks.
List<RouteStop> toUiRouteStops(api.Itinerary itinerary) {
  final stops = <RouteStop>[];
  var order = 1;

  for (final day in itinerary.days) {
    var offset = 0;
    for (var i = 0; i < day.pois.length; i++) {
      final poi = day.pois[i];
      final leg = i < day.transitLegs.length ? day.transitLegs[i] : null;
      final isLastOfDay = i == day.pois.length - 1;
      stops.add(RouteStop(
        order: order++,
        nameEn: poi.name,
        arrivalTime: clockLabel(offset),
        // No hop after the final stop of a day — the next stop belongs to a
        // different day and the planner routes no leg across that boundary.
        hop: (leg == null || isLastOfDay) ? null : toUiHop(leg),
      ));
      final stay = poi.stayMinutes > 0 ? poi.stayMinutes : _defaultStayMinutes;
      offset += stay + travelMinutesAfter(day.transitLegs, i, day.pois.length);
    }
  }
  return stops;
}

/// Carries a backend leg across, ODsay options included.
///
/// The options list is routinely empty — the backend skips ODsay for stops
/// within walking distance, and a spent daily quota (HTTP 429) yields the
/// same empty list. Neither is an error, so the hop still carries its
/// walk/car estimate and Kakao links.
TransitHop toUiHop(api.TransitLeg leg) => TransitHop(
      distanceKm: leg.distanceKm,
      walkMinutes: leg.walkMinutes,
      carMinutes: leg.carMinutes,
      kakaoWalkUrl: leg.kakaoWalkUrl,
      kakaoCarUrl: leg.kakaoCarUrl,
      options: [
        for (final option in leg.transitOptions)
          TransitChoice(
            label: option.typeLabel.isEmpty ? 'Transit' : option.typeLabel,
            segments: option.segments,
            totalMinutes: option.totalMinutes,
            fareWon: option.fareWon,
            transfers: option.transfers,
            walkMeters: option.walkMeters,
          ),
      ],
    );

Itinerary toUiItinerary(api.Itinerary itinerary, api.TravelState state) {
  return Itinerary(
    preferences: toUiPreferences(state),
    days: itinerary.days.map(toUiDay).toList(),
    routeStops: toUiRouteStops(itinerary),
    summary: itinerary.summary,
    sources: itinerary.sources.map(toUiSource).toList(),
    // Computed backend-side: overallScore prefers a flat overall_score and
    // otherwise reads critic_report.after, and feasibilityScore always comes
    // from critic_report.after. Recomputing that here would be a second
    // implementation of the same fallback chain.
    overallScore: itinerary.overallScore,
    feasibilityScore: itinerary.feasibilityScore,
    raw: itinerary.raw,
  );
}

TripSource toUiSource(api.ItinerarySource source) => TripSource(
      courseId: source.courseId,
      courseTitle: source.courseTitle,
      source: source.source,
      sourceUrl: source.sourceUrl,
    );

/// Shown as-is on Confirm Slots. A slot the traveller never answered comes
/// back null; the em dash keeps the row's shape rather than collapsing it.
TripPreferences toUiPreferences(api.TravelState state) {
  String slot(String? value) =>
      (value == null || value.trim().isEmpty) ? '—' : value.trim();

  return TripPreferences(
    dateRange: slot(state.travelDates),
    region: slot(state.region),
    travelStyle: slot(state.category),
    groupSize: slot(state.companion),
    dietaryNotes: slot(state.restrictions),
    pace: slot(state.pace),
  );
}

/// Names of the stops the traveller switched off, in the form POST
/// /revalidate's `excluded_ids` expects (see [toUiActivity] on why these are
/// names).
List<String> excludedIdsOf(Itinerary itinerary) => [
      for (final day in itinerary.days)
        for (final activity in day.activities)
          if (!activity.included) activity.id,
    ];
