import '../../models/plan_check.dart';
import '../../models/trip.dart';

/// Behind this interface a real backend (AI itinerary planner) can be
/// swapped in later without touching any UI code.
abstract class TripRepository {
  /// Returns null when the user has no itinerary yet (Trip_Empty-State).
  Future<Itinerary?> fetchCurrentItinerary();

  Future<TripPreferences> fetchDefaultPreferences();

  Future<Itinerary> generateItinerary(TripPreferences preferences);

  /// Applies the traveller's edits, re-runs Critic -> Repair -> Critic, and
  /// returns the repaired plan together with the critic's verdict either
  /// side of the repair.
  ///
  /// [swappedSlots] maps the name of a stop being replaced to the name of its
  /// replacement. Names, not ids: the backend has no stable POI id and
  /// matches on the normalised name.
  Future<(Itinerary, ReoptimizeResult)> reoptimizeItinerary(
    Itinerary itinerary, {
    Map<String, String> swappedSlots = const {},
  });

  /// Up to three ranked replacements for one slot, each with pre-computed
  /// warnings. [dayArea] is the day's neighbourhood key, which the backend
  /// uses to keep a replacement within walking distance of its neighbours.
  Future<List<SwapCandidate>> fetchSwapCandidates({
    required int day,
    required int slotIndex,
    required String currentPoi,
    required String dayArea,
    String currentPoiType,
    List<String> excludedIds,
  });
}
