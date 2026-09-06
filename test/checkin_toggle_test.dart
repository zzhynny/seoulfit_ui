import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/data/mock/mock_trip_repository.dart';
import 'package:seoulfit_ui/providers/trip_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<TripProvider> loaded() async {
    final provider = TripProvider(MockTripRepository());
    await provider.generateItinerary();
    return provider;
  }

  test('a stop can be marked visited', () async {
    // Nothing ever called checkIn: the check-in card's only tap handler went
    // to the missed-reason screen, so no stop could be stamped at all.
    final provider = await loaded();
    final stop = provider.itinerary!.days.first.activities
        .firstWhere((a) => !a.visited);

    provider.setVisited(stop.id, true);

    final after = provider.itinerary!.days
        .expand((d) => d.activities)
        .firstWhere((a) => a.id == stop.id);
    expect(after.visited, isTrue);
  });

  test('and un-marked again', () async {
    // The card is the only control on that screen, so a mis-tap needs a way
    // back or it strands a wrong stamp in the record.
    final provider = await loaded();
    final stop = provider.itinerary!.days.first.activities.first;

    provider.setVisited(stop.id, true);
    provider.setVisited(stop.id, false);

    final after = provider.itinerary!.days
        .expand((d) => d.activities)
        .firstWhere((a) => a.id == stop.id);
    expect(after.visited, isFalse);
  });

  test('stamping one stop leaves the others alone', () async {
    final provider = await loaded();
    final day = provider.itinerary!.days.first;
    final target = day.activities.first;
    final untouched = {
      for (final a in day.activities.skip(1)) a.id: a.visited,
    };

    provider.setVisited(target.id, true);

    final after = provider.itinerary!.days.first;
    for (final a in after.activities.skip(1)) {
      expect(a.visited, untouched[a.id], reason: a.id);
    }
  });
}
