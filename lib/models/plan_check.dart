/// Models for the two planner capabilities that had no UI: swapping a stop
/// for a ranked alternative, and reading the critic's verdict on the plan.
library;

/// A replacement offered for one itinerary slot by POST /swap-candidates.
class SwapCandidate {
  const SwapCandidate({
    required this.name,
    required this.type,
    required this.address,
    required this.warnings,
    this.lat,
    this.lng,
    this.rating,
    this.grade,
    this.distanceKm,
  });

  final String name;
  final String type;
  final String address;

  /// Pre-computed cautions from the backend, e.g. closed on the day this slot
  /// falls on. Shown as-is — the ranking already accounts for them, so these
  /// inform the choice rather than block it.
  final List<String> warnings;

  final double? lat;
  final double? lng;
  final double? rating;

  /// Michelin standing ("1 Michelin Star", "Bib Gourmand", ...) for restaurant
  /// candidates, which come from the curated set and carry no 5-point rating.
  final String? grade;

  /// Straight-line km from the stop being replaced. Restaurant candidates are
  /// ranked by this, so showing it explains the order.
  final double? distanceKm;

  /// The payload uses `poi_name`/`poi_type`, not `name`/`type` — the same
  /// record under different keys from the itinerary's own POIs.
  factory SwapCandidate.fromJson(Map<String, dynamic> json) => SwapCandidate(
        name: (json['poi_name'] ?? '').toString(),
        type: (json['poi_type'] ?? '').toString(),
        address: (json['address'] ?? '').toString(),
        warnings: [
          for (final w in (json['warnings'] as List? ?? const []))
            w.toString(),
        ],
        lat: (json['lat'] as num?)?.toDouble(),
        lng: (json['lng'] as num?)?.toDouble(),
        rating: (json['rating'] as num?)?.toDouble(),
        grade: json['grade']?.toString(),
        distanceKm: (json['distance_km'] as num?)?.toDouble(),
      );
}

/// One problem the critic found with the plan.
class PlanIssue {
  const PlanIssue({
    required this.code,
    required this.message,
    required this.severity,
    this.day,
    this.area,
  });

  final String code;
  final String message;
  final String severity;
  final int? day;
  final String? area;

  factory PlanIssue.fromJson(Map<String, dynamic> json) => PlanIssue(
        code: (json['code'] ?? '').toString(),
        message: (json['message'] ?? '').toString(),
        severity: (json['severity'] ?? '').toString(),
        day: (json['day'] as num?)?.toInt(),
        area: json['area']?.toString(),
      );
}

/// One pass of the critic over a plan. Scores are 0..1.
class CriticReport {
  const CriticReport({
    required this.issues,
    this.overallScore,
    this.feasibilityScore,
  });

  final List<PlanIssue> issues;

  /// Blends feasibility with requested-area coverage and foreigner-readiness.
  final double? overallScore;

  /// Meal windows, travel time between stops and opening hours only — the
  /// term that actually says whether a traveller can complete the plan.
  final double? feasibilityScore;

  static CriticReport fromJson(Map<String, dynamic> json) => CriticReport(
        overallScore: (json['overall_score'] as num?)?.toDouble(),
        feasibilityScore: (json['feasibility_score'] as num?)?.toDouble(),
        issues: [
          for (final i in (json['issues'] as List? ?? const []))
            if (i is Map) PlanIssue.fromJson(Map<String, dynamic>.from(i)),
        ],
      );

  static const empty = CriticReport(issues: []);
}

/// What POST /revalidate returns: the repaired plan, plus the critic's
/// verdict either side of the repair.
class ReoptimizeResult {
  const ReoptimizeResult({
    required this.before,
    required this.after,
    required this.repairLog,
  });

  final CriticReport before;
  final CriticReport after;

  /// Human-readable lines describing what the repair agent changed.
  final List<String> repairLog;

  /// Issues the repair agent resolved: present before, gone after.
  List<PlanIssue> get fixed {
    final remaining = after.issues.map((i) => i.code).toSet();
    return [
      for (final issue in before.issues)
        if (!remaining.contains(issue.code)) issue,
    ];
  }

  /// Issues that survived the repair and still need the traveller's call.
  List<PlanIssue> get remaining => after.issues;
}
