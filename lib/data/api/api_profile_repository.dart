import '../../models/profile.dart';
import '../../services/api_service.dart';
import '../../services/checkin_store.dart';
import '../../services/trip_storage_service.dart';
import '../repositories/profile_repository.dart';

/// [ProfileRepository] assembled from what the app already knows.
///
/// There is no profile endpoint and no account: the counts come from the
/// device's own check-in records, and the listed preferences from the planner
/// thread's collected slots. Nothing here is fetched from a user table
/// because none exists.
class ApiProfileRepository implements ProfileRepository {
  ApiProfileRepository(this._api, {this.displayName});

  final ApiService _api;

  /// The name entered during onboarding, held by `CompanionProvider`. Null
  /// before onboarding completes.
  final String? displayName;

  @override
  Future<UserProfile> fetchProfile() async {
    // `loadActive` rather than a thread lookup: ApiService.threadId is
    // regenerated on every launch and never persisted, so the check-in store's
    // own record of the last saved trip is the only way back to yesterday's
    // stamps.
    final trip = await CheckinStore.loadActive();
    final savedTrips = await TripStorageService.getTrips();

    final plannedDays = trip?.planned.length ?? 0;
    final stampedDays = trip?.checkins.entries
            .where((e) => e.value.visited.isNotEmpty)
            .length ??
        0;
    final spotsVisited = trip?.checkins.values
            .fold<int>(0, (sum, day) => sum + day.visited.length) ??
        0;

    return UserProfile(
      name: displayName?.trim().isNotEmpty == true
          ? displayName!.trim()
          : 'Traveler',
      explorerBadge: _badgeFor(spotsVisited),
      stampsCollected: stampedDays,
      stampsTotal: plannedDays,
      spotsVisited: spotsVisited,
      savedRecaps: savedTrips.length,
      preferences: await _preferences(),
    );
  }

  /// The slots the planner collected, as chips. Skips whatever the traveller
  /// never answered rather than showing empty pills.
  Future<List<String>> _preferences() async {
    try {
      final state = await _api.getState();
      return [
        for (final value in [state.pace, state.restrictions])
          if (value != null && value.trim().isNotEmpty) value.trim(),
      ];
    } catch (_) {
      // Profile must still render with the backend unreachable — the counts
      // above are all local.
      return const [];
    }
  }
}

/// ponytail: flat thresholds. Real badge tiers would come from the backend
/// once there's an account to hang them on.
String _badgeFor(int spotsVisited) {
  if (spotsVisited >= 20) return 'Seoul Native';
  if (spotsVisited >= 10) return 'City Explorer';
  if (spotsVisited >= 1) return 'First Steps';
  return 'New Arrival';
}
