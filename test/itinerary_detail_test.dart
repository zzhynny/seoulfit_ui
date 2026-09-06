import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/models/trip.dart';
import 'package:seoulfit_ui/widgets/itinerary_detail.dart';

Widget host(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  group('PlanScoreChip', () {
    testWidgets('leads with feasibility, not the blended score',
        (tester) async {
      // Feasibility is the only term that says whether the days can be
      // completed; overall folds in area coverage and foreigner-readiness.
      await tester.pumpWidget(host(
        const PlanScoreChip(feasibility: 0.94, overall: 0.72),
      ));

      expect(find.text('Doable 94%'), findsOneWidget);
      expect(find.text('Doable 72%'), findsNothing);
    });

    testWidgets('shows nothing at all for an unscored plan', (tester) async {
      // A 0% would read as "scored, and terrible" rather than "never scored".
      await tester.pumpWidget(host(const PlanScoreChip(feasibility: null)));

      expect(find.byType(Text), findsNothing);
    });

    testWidgets('falls back to the overall score when feasibility is absent',
        (tester) async {
      await tester.pumpWidget(host(const PlanScoreChip(feasibility: null, overall: 0.8)));

      expect(find.text('80%'), findsOneWidget);
    });
  });

  group('SourcesCard', () {
    testWidgets('renders one chip per course', (tester) async {
      await tester.pumpWidget(host(const SourcesCard(sources: [
        TripSource(
          courseTitle: 'Seoul Palace Walking Course',
          source: 'Visit Seoul',
          sourceUrl: 'https://english.visitseoul.net/',
        ),
        TripSource(
          courseTitle: '',
          source: 'Korea Tourism Organization',
          sourceUrl: '',
        ),
      ])));

      expect(find.text('Seoul Palace Walking Course'), findsOneWidget);
      // A course with no title falls back to its publisher rather than
      // rendering an empty chip.
      expect(find.text('Korea Tourism Organization'), findsOneWidget);
    });

    testWidgets('collapses when the plan cites nothing', (tester) async {
      await tester.pumpWidget(host(const SourcesCard(sources: [])));

      expect(find.text('Built from'), findsNothing);
    });
  });

  group('DayCostChip', () {
    testWidgets('shows the planner\'s estimate verbatim', (tester) async {
      await tester.pumpWidget(host(
        const DayCostChip(estimatedCost: '60,000 - 80,000 KRW'),
      ));

      expect(find.text('60,000 - 80,000 KRW'), findsOneWidget);
    });

    testWidgets('collapses when the planner gave no estimate', (tester) async {
      await tester.pumpWidget(host(const DayCostChip(estimatedCost: '   ')));

      expect(find.byType(Text), findsNothing);
    });
  });
}
