/// Category of a single itinerary activity — drives the tag color.
enum ActivityCategory { culture, food, shopping, crafts, teaHouse, nature }

extension ActivityCategoryX on ActivityCategory {
  String get label {
    switch (this) {
      case ActivityCategory.culture:
        return 'Culture';
      case ActivityCategory.food:
        return 'Food';
      case ActivityCategory.shopping:
        return 'Shopping';
      case ActivityCategory.crafts:
        return 'Crafts';
      case ActivityCategory.teaHouse:
        return 'Tea House';
      case ActivityCategory.nature:
        return 'Nature';
    }
  }
}

class TripActivity {
  const TripActivity({
    required this.id,
    required this.time,
    required this.category,
    required this.title,
    required this.description,
    this.imageAsset,
    this.included = true,
    this.visited = false,
    this.aiInsight,
  });

  final String id;
  final String time;
  final ActivityCategory category;
  final String title;
  final String description;
  final String? imageAsset;
  final bool included;
  final bool visited;
  final String? aiInsight;

  TripActivity copyWith({bool? included, bool? visited}) => TripActivity(
        id: id,
        time: time,
        category: category,
        title: title,
        description: description,
        imageAsset: imageAsset,
        included: included ?? this.included,
        visited: visited ?? this.visited,
        aiInsight: aiInsight,
      );
}

enum MissedReason { notEnoughTime, tooTired, didntFeelLikeIt, other }

class TripDay {
  const TripDay({
    required this.dayNumber,
    required this.date,
    required this.areaName,
    required this.activities,
  });

  final int dayNumber;
  final String date;
  final String areaName;
  final List<TripActivity> activities;

  int get visitedCount => activities.where((a) => a.visited).length;
}

class TripPreferences {
  const TripPreferences({
    required this.dateRange,
    required this.duration,
    required this.travelStyle,
    required this.groupSize,
    required this.dietaryNotes,
  });

  final String dateRange;
  final String duration;
  final String travelStyle;
  final String groupSize;
  final String dietaryNotes;
}

class RouteStop {
  const RouteStop({
    required this.order,
    required this.nameEn,
    this.nameKo,
    required this.arrivalTime,
    this.transitMode,
    this.transitDetail,
    this.exitInstruction,
  });

  final int order;
  final String nameEn;
  final String? nameKo;
  final String arrivalTime;
  final String? transitMode;
  final String? transitDetail;
  final String? exitInstruction;
}

class Itinerary {
  Itinerary({
    required this.preferences,
    required this.days,
    required this.routeStops,
  });

  final TripPreferences preferences;
  final List<TripDay> days;
  final List<RouteStop> routeStops;

  int get stampedDays => days.where((d) => d.visitedCount > 0).length;
}
