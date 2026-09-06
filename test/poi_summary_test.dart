import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/services/api_service.dart';
import 'package:seoulfit_ui/widgets/poi_summary.dart';

Widget host(Widget child, {ApiService? api}) => MaterialApp(
      home: Provider<ApiService?>.value(
        value: api,
        child: Scaffold(body: child),
      ),
    );

void main() {
  testWidgets('shows the planner note immediately, not a spinner',
      (tester) async {
    // The lookup is a Gemini call. Leaving the line blank or spinning while
    // it runs is what made the itinerary look empty on open.
    await tester.pumpWidget(host(const PoiSummary(
      name: 'Gyeongbokgung Palace',
      fallback: 'Seoul\'s main royal palace, first built in 1395.',
    )));

    expect(find.text("Seoul's main royal palace, first built in 1395."),
        findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });

  testWidgets('keeps the fallback when there is no backend to ask',
      (tester) async {
    // The mock build provides a null ApiService.
    await tester.pumpWidget(host(const PoiSummary(
      name: 'Bukchon Hanok Village',
      fallback: 'A hillside of restored hanok houses.',
    )));
    await tester.pumpAndSettle();

    expect(find.text('A hillside of restored hanok houses.'), findsOneWidget);
  });

  testWidgets('an empty fallback still renders rather than throwing',
      (tester) async {
    // toUiActivity falls back to the address, but a POI with neither notes
    // nor address yields an empty string.
    await tester.pumpWidget(host(const PoiSummary(name: 'Nowhere', fallback: '')));
    await tester.pumpAndSettle();

    expect(find.byType(PoiSummary), findsOneWidget);
  });
}
