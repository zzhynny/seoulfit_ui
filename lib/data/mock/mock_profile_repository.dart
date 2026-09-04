import '../../models/profile.dart';
import '../repositories/profile_repository.dart';

class MockProfileRepository implements ProfileRepository {
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
}
