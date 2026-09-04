/// The five selectable travel-buddy companions.
enum CompanionId { tiger, bear, dog, duck, rabbit }

extension CompanionIdX on CompanionId {
  String get key => name;
}

/// One companion's display info + every pose-state asset path, generated
/// from the fixed naming pattern:
///  - `buddy_ANIMAL.png`            (default / select-screen portrait)
///  - `ANIMAL-guide-chat.png`       (speaking / guide pose)
///  - `ANIMAL-lost-map.png`         (map-worried pose)
///  - `ANIMAL-walking-loading.png`  (walking / loading pose)
///  - `buddy-ANIMAL-complete.png`   (celebrating pose)
class Companion {
  const Companion({
    required this.id,
    required this.displayName,
    required this.portraitAsset,
    required this.guideChatAsset,
    required this.lostMapAsset,
    required this.walkingLoadingAsset,
    required this.completeAsset,
  });

  final CompanionId id;
  final String displayName;

  /// Default / select-screen portrait.
  final String portraitAsset;

  /// Speaking / guide pose — chat avatar.
  final String guideChatAsset;

  /// Map-worried pose — lost / help states.
  final String lostMapAsset;

  /// Walking pose — loading screens.
  final String walkingLoadingAsset;

  /// Celebrating pose — day-complete / trip-finish.
  final String completeAsset;

  factory Companion.forAnimal(CompanionId id, String displayName) {
    final animal = id.key;
    return Companion(
      id: id,
      displayName: displayName,
      portraitAsset: 'assets/images/buddy_$animal.png',
      guideChatAsset: 'assets/images/$animal-guide-chat.png',
      lostMapAsset: 'assets/images/$animal-lost-map.png',
      walkingLoadingAsset: 'assets/images/$animal-walking-loading.png',
      completeAsset: 'assets/images/buddy-$animal-complete.png',
    );
  }
}

/// Registry of all companions, generated from [CompanionId].
final Map<CompanionId, Companion> kCompanions = {
  CompanionId.tiger: Companion.forAnimal(CompanionId.tiger, 'Tiger'),
  CompanionId.bear: Companion.forAnimal(CompanionId.bear, 'Bear'),
  CompanionId.dog: Companion.forAnimal(CompanionId.dog, 'Dog'),
  CompanionId.duck: Companion.forAnimal(CompanionId.duck, 'Duck'),
  CompanionId.rabbit: Companion.forAnimal(CompanionId.rabbit, 'Rabbit'),
};

/// Companions in the fixed select-grid display order (row 1: tiger, bear,
/// rabbit / row 2: duck, dog), matching the Figma character grid.
List<Companion> get kCompanionGridOrder => [
      kCompanions[CompanionId.tiger]!,
      kCompanions[CompanionId.bear]!,
      kCompanions[CompanionId.rabbit]!,
      kCompanions[CompanionId.duck]!,
      kCompanions[CompanionId.dog]!,
    ];
