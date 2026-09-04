import '../../models/profile.dart';
import '../repositories/profile_repository.dart';

class MockProfileRepository implements ProfileRepository {
  /// Days with at least one check-in stamp. Bump this below 3 to preview
  /// the low-data Trip Recap variant instead of the full journey map.
  static const int _stampedDayCount = 3;

  @override
  Future<UserProfile> fetchProfile() async {
    await Future.delayed(const Duration(milliseconds: 150));
    return const UserProfile(
      name: 'Alex',
      explorerBadge: 'Seoul Explorer',
      stampsCollected: 3,
      stampsTotal: 5,
      spotsVisited: 3,
      savedRecaps: 1,
      preferences: ['Culture & K-Pop', 'Vegan Options', 'Relaxed'],
    );
  }

  @override
  Future<List<RecapStampDay>> fetchStampDays() async {
    await Future.delayed(const Duration(milliseconds: 100));
    return const [
      RecapStampDay(dayNumber: 1, state: StampState.visited, label: 'Stamped'),
      RecapStampDay(dayNumber: 2, state: StampState.empty, label: 'Empty'),
      RecapStampDay(dayNumber: 3, state: StampState.partial, label: 'Started'),
      RecapStampDay(dayNumber: 4, state: StampState.empty, label: 'Empty'),
      RecapStampDay(dayNumber: 5, state: StampState.empty, label: 'Empty'),
    ];
  }

  @override
  Future<List<RecapStop>> fetchRecapStops() async {
    await Future.delayed(const Duration(milliseconds: 100));
    return const [
      RecapStop(name: 'Jongno', dayLabel: 'Day 1 • 3/4 Visited', visited: true),
      RecapStop(name: 'Bukchon', dayLabel: 'Day 2 • All Visited', visited: true),
      RecapStop(name: 'Namsan', dayLabel: 'Day 3 • 2/3 Visited', visited: true),
      RecapStop(name: 'Dongdaemun', dayLabel: 'Day 4 • Planned', visited: false),
      RecapStop(name: 'Yeouido', dayLabel: 'Day 5 • Planned', visited: false),
    ];
  }

  @override
  Future<bool> hasEnoughDataForFullRecap() async {
    return _stampedDayCount >= 3;
  }
}
