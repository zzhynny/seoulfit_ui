enum ChatSender { bot, user }

class ChatMessage {
  const ChatMessage({
    required this.sender,
    required this.text,
    this.showTravelerSelector = false,
  });

  final ChatSender sender;
  final String text;
  final bool showTravelerSelector;
}

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
