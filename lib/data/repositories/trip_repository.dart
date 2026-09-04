import '../../models/trip.dart';

/// Behind this interface a real backend (AI itinerary planner) can be
/// swapped in later without touching any UI code.
abstract class TripRepository {
  /// Returns null when the user has no itinerary yet (Trip_Empty-State).
  Future<Itinerary?> fetchCurrentItinerary();

  Future<TripPreferences> fetchDefaultPreferences();

  Future<Itinerary> generateItinerary(TripPreferences preferences);

  Future<Itinerary> reoptimizeItinerary(Itinerary itinerary);
}
