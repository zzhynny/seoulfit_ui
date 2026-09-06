import '../../models/travel_state.dart' as api;
import '../../models/trip.dart';
import '../../services/api_service.dart';
import '../repositories/trip_repository.dart';
import 'mappers.dart';

/// [TripRepository] backed by the FastAPI planner.
///
/// Shares one [ApiService] — and therefore one `thread_id` — with
/// [ApiChatRepository]: the itinerary is produced by the chat conversation,
/// not by a separate planning endpoint, so a second thread would plan against
/// an empty set of answers.
class ApiTripRepository implements TripRepository {
  ApiTripRepository(this._api);

  final ApiService _api;

  @override
  Future<Itinerary?> fetchCurrentItinerary() async {
    final state = await _api.getState();
    final itinerary = state.itinerary;
    if (itinerary == null) return null;
    return toUiItinerary(itinerary, state);
  }

  @override
  Future<TripPreferences> fetchDefaultPreferences() async {
    return toUiPreferences(await _api.getState());
  }

  /// The backend has no generate-from-preferences endpoint: the itinerary
  /// arrives as a side effect of the chat turn that confirms the answers
  /// already collected. [preferences] is what the user was just shown on
  /// Confirm Slots and is already the backend's own state, so it is not
  /// re-sent — pressing Generate only says "yes" to it.
  ///
  /// 'confirm' is one of the literal trigger words `_after_collect` routes on
  /// (`confirm` / `yes` / `ok` / `go` / `generate`), so it reaches
  /// `handle_confirm` without depending on intent classification.
  @override
  Future<Itinerary> generateItinerary(TripPreferences preferences) async {
    final state = await _api.chat(
      'confirm',
      // This turn runs retrieval, the planner and critic-repair end to end.
      // The conversational timeout silently fails it.
      timeout: ApiService.generationTimeout,
    );

    final itinerary = state.itinerary;
    if (itinerary == null) {
      throw StateError(
        'The planner returned no itinerary. Backend said: '
        '${state.reply ?? "(nothing)"}',
      );
    }
    return toUiItinerary(itinerary, state);
  }

  /// Re-runs Critic → Repair → Critic with the stops the user switched off on
  /// "Make This Trip Yours" removed, and persists the result on the thread so
  /// later edits build on it.
  @override
  Future<Itinerary> reoptimizeItinerary(Itinerary itinerary) async {
    final response = await _api.revalidate(
      excludedIds: excludedIdsOf(itinerary),
    );

    final repaired = response['repaired_itinerary'];
    if (repaired is! Map) {
      throw StateError('Revalidate returned no repaired itinerary.');
    }

    // Preferences aren't part of the revalidate response — carry over the
    // ones already on screen rather than spending a round-trip on /state.
    final rebuilt = api.Itinerary.fromJson(Map<String, dynamic>.from(repaired));
    return Itinerary(
      preferences: itinerary.preferences,
      days: rebuilt.days.map(toUiDay).toList(),
      routeStops: toUiRouteStops(rebuilt),
    );
  }
}
