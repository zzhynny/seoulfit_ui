import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/data/mock/mock_trip_repository.dart';
import 'package:seoulfit_ui/models/trip.dart';
import 'package:seoulfit_ui/models/trip_checkin.dart';
import 'package:seoulfit_ui/providers/trip_provider.dart';
import 'package:seoulfit_ui/services/checkin_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<TripProvider> loadedProvider() async {
    final provider = TripProvider(MockTripRepository());
    // The mock starts with no trip (the Trip tab's empty state), so generate
    // one rather than loading nothing.
    await provider.generateItinerary();
    return provider;
  }

  test('a check-in reaches local storage, not just memory', () async {
    // Profile's stamp and spot counts read CheckinStore. Before this, nothing
    // ever wrote to it, so those counts were permanently zero and the recap
    // could not survive a restart.
    final provider = await loadedProvider();
    final first = provider.itinerary!.days.first.activities.first;

    provider.setVisited(first.id, true);
    await Future<void>.delayed(const Duration(milliseconds: 50));

    final saved = await CheckinStore.loadActive();
    expect(saved, isNotNull);
    expect(saved!.checkins[1]!.visited, contains(first.id));
    expect(saved.planned[1], contains(first.id));
  });

  test('a missed stop is recorded with its reason', () async {
    final provider = await loadedProvider();
    final day = provider.itinerary!.days.first;
    final activity = day.activities.first;

    provider.markMissed(activity.id, MissedReason.tooTired);
    await Future<void>.delayed(const Duration(milliseconds: 50));

    final saved = await CheckinStore.loadActive();
    expect(saved!.checkins[1]!.misses[activity.id], MissReason.stamina);
  });

  test('untouched days stay unrecorded rather than recorded as empty',
      () async {
    // Every aggregate excludes an unrecorded day. Writing it as an empty
    // DayCheckin would read as "went nowhere that day" instead.
    final provider = await loadedProvider();
    provider.setVisited(provider.itinerary!.days.first.activities.first.id, true);
    await Future<void>.delayed(const Duration(milliseconds: 50));

    final saved = await CheckinStore.loadActive();

    // Recorded days are exactly the days that actually have something on
    // them — derived from the itinerary rather than assumed, since the mock
    // seeds some days as already visited.
    final expected = {
      for (final day in provider.itinerary!.days)
        if (day.activities.any((a) => a.visited)) day.dayNumber,
    };
    expect(saved!.checkins.keys.toSet(), expected);

    // Every day is still planned, whether or not it was recorded.
    expect(saved.planned.keys.toSet(),
        provider.itinerary!.days.map((d) => d.dayNumber).toSet());
    for (final entry in saved.checkins.entries) {
      expect(entry.value.visited.isNotEmpty || entry.value.misses.isNotEmpty,
          isTrue,
          reason: 'day ${entry.key} was written with nothing on it');
    }
  });

  test('the trip id is minted once and reused across check-ins', () async {
    // ApiService.threadId is regenerated every launch; reusing it here would
    // orphan yesterday's stamps.
    final provider = await loadedProvider();
    final activities = provider.itinerary!.days.first.activities;

    provider.setVisited(activities.first.id, true);
    await Future<void>.delayed(const Duration(milliseconds: 50));
    final firstId = provider.tripId;

    provider.setVisited(activities.last.id, true);
    await Future<void>.delayed(const Duration(milliseconds: 50));

    expect(provider.tripId, firstId);
    expect(firstId, isNotNull);
  });

  test('a check-in keeps the trip-level fields it never touches', () async {
    // _mutateActivity rebuilds the Itinerary and every TripDay around the one
    // changed stop. Listing the fields by hand there dropped summary,
    // sources, scores and per-day cost the moment they were added, so
    // checking in silently emptied the itinerary screens.
    final provider = await loadedProvider();
    final before = provider.itinerary!;
    expect(before.summary, isNotEmpty, reason: 'fixture must have a summary');
    expect(before.sources, isNotEmpty);
    expect(before.days.first.estimatedCost, isNotEmpty);

    provider.setVisited(before.days.first.activities.first.id, true);
    final after = provider.itinerary!;

    expect(after.summary, before.summary);
    expect(after.sources.length, before.sources.length);
    expect(after.overallScore, before.overallScore);
    expect(after.feasibilityScore, before.feasibilityScore);
    expect(after.days.first.estimatedCost, before.days.first.estimatedCost);
    // And the check-in itself still happened.
    expect(after.days.first.activities.first.visited, isTrue);
  });
}
