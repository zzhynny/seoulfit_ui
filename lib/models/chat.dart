enum ChatSender { bot, user }

class ChatMessage {
  const ChatMessage({
    required this.sender,
    required this.text,
    this.showTravelerSelector = false,
    this.readyToBuild = false,
    this.quickReplies = const [],
    this.awaitingField,
    this.awaitingStep,
  });

  final ChatSender sender;
  final String text;

  /// Renders the inline +/- traveller stepper under this bubble.
  final bool showTravelerSelector;

  /// One-tap answers offered under the composer for the question this
  /// message asked. Deliberately sparse — see [ApiChatRepository] for why
  /// most steps offer none.
  final List<String> quickReplies;

  /// The backend's `current_field` — the one slot this message is asking
  /// about. Drives the calendar affordance, which only makes sense while the
  /// buddy is waiting on `travel_dates`.
  final String? awaitingField;

  /// The backend's `current_step` this message was sent from — 'collecting',
  /// 'day_plan' or 'confirm'. `day_plan` is what reveals the "Plan each day"
  /// CTA, since that step needs the Day Planner screen rather than a chip.
  final String? awaitingStep;

  /// Reveals the "Build My Itinerary" CTA. Separate from
  /// [showTravelerSelector] because the two coincide only in the mock: the
  /// real backend collects `companion` as free text over chat and signals
  /// readiness with `current_step == 'confirm'`, with no stepper involved.
  final bool readyToBuild;
}

/// The on-trip help destinations. Routed on instead of the card title so
/// rewording a card can't silently break navigation.
enum LiveHelpTopic { passport, emergency, nearby, explore, shopping }

/// The On-Trip help entry points. Static presentation copy, identical for
/// mock and live builds — the backend supplies what's *behind* each card
/// (POST /nearby, /emergency-rooms, /nearby-poi, /nearby-shopping), never the
/// cards themselves.
///
/// Five, not the three the Figma frame drew: the backend has five live-help
/// endpoints, and a card is the only way to reach one.
const List<OnTripHelpTopic> kOnTripTopics = [
  OnTripHelpTopic(
    emoji: '🛂',
    title: 'Lost Passport',
    badge: 'urgent',
    description: 'Find your embassy in Seoul, with report guidelines',
    topic: LiveHelpTopic.passport,
  ),
  OnTripHelpTopic(
    emoji: '🏥',
    title: 'Emergency Room',
    badge: '911',
    description: 'Nearest ER with live bed availability',
    topic: LiveHelpTopic.emergency,
  ),
  OnTripHelpTopic(
    emoji: '📍',
    title: 'Near Me',
    badge: 'utility',
    description: 'Open cafes and restaurants within walking distance',
    topic: LiveHelpTopic.nearby,
  ),
  OnTripHelpTopic(
    emoji: '🏛',
    title: 'Explore Nearby',
    badge: 'sights',
    description: 'Museums, parks and landmarks around you',
    topic: LiveHelpTopic.explore,
  ),
  OnTripHelpTopic(
    emoji: '🛍',
    title: 'Shopping',
    badge: 'shops',
    description: 'Markets, malls and local shops near you',
    topic: LiveHelpTopic.shopping,
  ),
];

class OnTripHelpTopic {
  const OnTripHelpTopic({
    required this.emoji,
    required this.title,
    required this.badge,
    required this.description,
    required this.topic,
  });

  final String emoji;
  final String title;
  final String badge;
  final String description;

  /// Which live-help view this card opens.
  final LiveHelpTopic topic;
}
