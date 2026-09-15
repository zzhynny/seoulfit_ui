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

/// Stands in for ApiService's name-keyed memo: [saved] is what it already
/// holds, and every real lookup is counted.
class _FakeApi extends ApiService {
  _FakeApi(this.saved);

  final Map<String, String> saved;
  int lookups = 0;

  @override
  String? cachedPoiSummary(String name) => saved[name];

  @override
  Future<String> fetchPoiSummary(String name, {String type = ''}) async {
    lookups++;
    return saved[name] = 'Fetched description';
  }
}

void main() {
  testWidgets('a description already fetched shows on the first frame',
      (tester) async {
    // Every screen builds its own card. Showing the planner note first and
    // then swapping the description in read as "regenerating" on each screen.
    final api = _FakeApi({'Gyeongbokgung Palace': 'The main royal palace of Joseon.'});
    await tester.pumpWidget(host(
      const PoiSummary(name: 'Gyeongbokgung Palace', fallback: 'planner note'),
      api: api,
    ));

    expect(find.text('The main royal palace of Joseon.'), findsOneWidget);
    expect(find.text('planner note'), findsNothing);
    expect(api.lookups, 0);
  });

  testWidgets('a new description is fetched once, then kept on every screen',
      (tester) async {
    final api = _FakeApi({});
    await tester.pumpWidget(host(
      const PoiSummary(name: 'Bukchon Hanok Village', fallback: 'planner note'),
      api: api,
    ));
    expect(find.text('planner note'), findsOneWidget);

    await tester.pump();
    expect(find.text('Fetched description'), findsOneWidget);

    // Another screen builds a brand-new card for the same stop.
    await tester.pumpWidget(host(
      const PoiSummary(key: ValueKey('other screen'), name: 'Bukchon Hanok Village', fallback: 'planner note'),
      api: api,
    ));
    expect(find.text('Fetched description'), findsOneWidget);
    expect(api.lookups, 1);
  });

  testWidgets('switching day tabs shows the new stop, not the old one',
      (tester) async {
    // Day tabs rebuild the list with unkeyed cards, so the same State gets a
    // different stop. It used to keep the previous day's text (and photo).
    final api = _FakeApi({'Gyeongbokgung Palace': 'Palace text', 'N Seoul Tower': 'Tower text'});
    await tester.pumpWidget(host(
      const PoiSummary(name: 'Gyeongbokgung Palace', fallback: ''),
      api: api,
    ));
    expect(find.text('Palace text'), findsOneWidget);

    await tester.pumpWidget(host(
      const PoiSummary(name: 'N Seoul Tower', fallback: ''),
      api: api,
    ));
    expect(find.text('Tower text'), findsOneWidget);
  });

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
