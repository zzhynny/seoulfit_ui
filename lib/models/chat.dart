enum ChatSender { bot, user }

class ChatMessage {
  const ChatMessage({
    required this.sender,
    required this.text,
    this.showTravelerSelector = false,
    this.readyToBuild = false,
  });

  final ChatSender sender;
  final String text;

  /// Renders the inline +/- traveller stepper under this bubble.
  final bool showTravelerSelector;

  /// Reveals the "Build My Itinerary" CTA. Separate from
  /// [showTravelerSelector] because the two coincide only in the mock: the
  /// real backend collects `companion` as free text over chat and signals
  /// readiness with `current_step == 'confirm'`, with no stepper involved.
  final bool readyToBuild;
}

/// The three On-Trip help entry points. Static presentation copy, identical
/// for mock and live builds — the backend supplies what's *behind* each card
/// (POST /nearby, /emergency-rooms), never the cards themselves.
const List<OnTripHelpTopic> kOnTripTopics = [
  OnTripHelpTopic(
    emoji: '🛂',
    title: 'Lost Passport',
    badge: 'urgent',
    description: 'Get instant embassies map & local report guidelines',
  ),
  OnTripHelpTopic(
    emoji: '🏥',
    title: 'Emergency Room',
    badge: '911',
    description: 'English-speaking hospitals & clinics nearby',
  ),
  OnTripHelpTopic(
    emoji: '📍',
    title: 'Near Me',
    badge: 'utility',
    description: 'Public transit, baggage storage & tourist centers',
  ),
];

class OnTripHelpTopic {
  const OnTripHelpTopic({
    required this.emoji,
    required this.title,
    required this.badge,
    required this.description,
  });

  final String emoji;
  final String title;
  final String badge;
  final String description;
}
