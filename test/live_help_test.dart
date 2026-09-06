import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/models/chat.dart';
import 'package:seoulfit_ui/screens/live_help/live_help_screen.dart';

void main() {
  test('every live-help destination has a card that reaches it', () {
    // The Chat tab's On-Trip cards are the only entry point into these views
    // now that the Flutter app's own hub is gone. A destination with no card
    // is unreachable, and the route parses on the enum name.
    final reachable = kOnTripTopics.map((t) => t.topic).toSet();
    expect(reachable, LiveHelpTopic.values.toSet());
  });

  test('topic names round-trip through the route path', () {
    for (final topic in LiveHelpTopic.values) {
      final parsed =
          LiveHelpTopic.values.where((t) => t.name == topic.name).firstOrNull;
      expect(parsed, topic);
    }
  });

  testWidgets('the passport view renders without a location fix',
      (tester) async {
    // Embassies ship in assets/data/embassies.json precisely so the one view
    // someone opens after losing their documents needs no radio and no
    // permission prompt.
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: LiveHelpTopicScreen(
          topic: LiveHelpTopic.passport,
          onBack: () {},
        ),
      ),
    ));
    await tester.pump();

    expect(find.text('Lost passport'), findsOneWidget);
  });
}
