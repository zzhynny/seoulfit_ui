import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/models/plan_check.dart';

CriticReport report(List<String> codes, {double? overall, double? feas}) =>
    CriticReport(
      overallScore: overall,
      feasibilityScore: feas,
      issues: [
        for (final c in codes)
          PlanIssue(code: c, message: c, severity: 'warn'),
      ],
    );

void main() {
  group('SwapCandidate.fromJson', () {
    test('reads the payload\'s poi_name/poi_type keys', () {
      // The candidate payload names these differently from the itinerary's
      // own POIs, which use name/type. Reading the wrong pair yields blank
      // rows that look like a backend failure.
      final c = SwapCandidate.fromJson(const {
        'poi_name': 'Onion Anguk',
        'poi_type': 'cafe',
        'address': '5 Gyedong-gil, Jongno-gu',
        'lat': 37.5789,
        'lng': 126.9856,
        'rating': 4.5,
        'warnings': ['Closed on the day this slot falls on'],
      });

      expect(c.name, 'Onion Anguk');
      expect(c.type, 'cafe');
      expect(c.rating, 4.5);
      expect(c.warnings, hasLength(1));
    });

    test('survives a candidate with nothing but a name', () {
      final c = SwapCandidate.fromJson(const {'poi_name': 'Somewhere'});
      expect(c.name, 'Somewhere');
      expect(c.warnings, isEmpty);
      expect(c.lat, isNull);
      expect(c.rating, isNull);
    });
  });

  group('ReoptimizeResult', () {
    test('splits issues the repair resolved from those it did not', () {
      final result = ReoptimizeResult(
        before: report(['CLOSED_ON_ASSIGNED_DAY', 'MEAL_WINDOW']),
        after: report(['MEAL_WINDOW']),
        repairLog: const ['Moved Gyeongbokgung to 09:00'],
      );

      expect(result.fixed.map((i) => i.code), ['CLOSED_ON_ASSIGNED_DAY']);
      expect(result.remaining.map((i) => i.code), ['MEAL_WINDOW']);
    });

    test('a clean pass reports nothing on either side', () {
      final result = ReoptimizeResult(
        before: report(const []),
        after: report(const []),
        repairLog: const [],
      );

      expect(result.fixed, isEmpty);
      expect(result.remaining, isEmpty);
    });
  });

  test('CriticReport reads the scores the backend actually sends', () {
    // Shape taken from a live critic_report.after.
    final r = CriticReport.fromJson(const {
      'overall_score': 0.87,
      'feasibility_score': 1.0,
      'duplicate_score': 1.0,
      'issues': [
        {
          'code': 'MEAL_WINDOW',
          'message': 'No lunch stop between 11:00 and 14:00 on day 2.',
          'severity': 'warn',
          'day': 2,
          'area': 'hongdae',
        }
      ],
    });

    expect(r.overallScore, 0.87);
    expect(r.feasibilityScore, 1.0);
    expect(r.issues.single.day, 2);
    expect(r.issues.single.area, 'hongdae');
  });
}
