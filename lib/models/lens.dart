class LensPlaceResult {
  const LensPlaceResult({
    required this.name,
    required this.address,
    required this.confidence,
    required this.hours,
    required this.openDays,
    required this.closedNote,
    required this.gettingThere,
    required this.hashtags,
    required this.audioGuideCategory,
    required this.audioGuideTitle,
    required this.audioGuideExcerpt,
  });

  final String name;
  final String address;
  final int confidence;
  final String hours;
  final String openDays;
  final String closedNote;
  final String gettingThere;
  final List<String> hashtags;
  final String audioGuideCategory;
  final String audioGuideTitle;
  final String audioGuideExcerpt;
}
