class UserProfile {
  const UserProfile({
    required this.name,
    required this.explorerBadge,
    required this.stampsCollected,
    required this.stampsTotal,
    required this.spotsVisited,
    required this.savedRecaps,
    required this.preferences,
  });

  final String name;
  final String explorerBadge;
  final int stampsCollected;
  final int stampsTotal;
  final int spotsVisited;
  final int savedRecaps;
  final List<String> preferences;
}

enum StampState { visited, partial, empty }

class RecapStampDay {
  const RecapStampDay({
    required this.dayNumber,
    required this.state,
    required this.label,
  });

  final int dayNumber;
  final StampState state;
  final String label;
}

class RecapStop {
  const RecapStop({
    required this.name,
    required this.dayLabel,
    required this.state,
  });

  final String name;
  final String dayLabel;
  final StampState state;
}
