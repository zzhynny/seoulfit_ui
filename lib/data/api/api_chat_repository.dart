import '../../models/chat.dart';
import '../../models/travel_state.dart';
import '../../services/api_service.dart';
import '../repositories/chat_repository.dart';

/// [ChatRepository] backed by the FastAPI planner's conversational intake.
///
/// Shares its [ApiService] — and so its `thread_id` — with
/// [ApiTripRepository]: this conversation *is* how the itinerary gets built,
/// so the two must read and write the same LangGraph thread.
class ApiChatRepository implements ChatRepository {
  ApiChatRepository(this._api);

  final ApiService _api;

  /// Opens the conversation. `null` asks the backend for its greeting rather
  /// than sending a turn.
  ///
  /// The backend keeps history server-side in the LangGraph checkpoint and
  /// exposes only the latest AI message, so there is no transcript to
  /// restore — a returning user sees one bubble, not their scrollback.
  @override
  Future<List<ChatMessage>> fetchConversation() async {
    return [_botMessage(await _api.chat(null))];
  }

  @override
  Future<ChatMessage> sendMessage(String text) async {
    return _botMessage(await _api.chat(text));
  }

  @override
  List<OnTripHelpTopic> onTripTopics() => kOnTripTopics;

  ChatMessage _botMessage(TravelState state) {
    return ChatMessage(
      sender: ChatSender.bot,
      text: state.reply ?? '',
      // `confirm` is the step where the graph has every slot it needs and is
      // waiting on a yes — exactly when the "Build My Itinerary" CTA should
      // appear. Pressing it lands on Confirm Slots, which reads the same
      // state back via GET /state.
      readyToBuild: state.currentStep == 'confirm',
      quickReplies: _quickRepliesFor(state.currentStep),
    );
  }
}

/// One-tap answers for the step the backend is on.
///
/// This is deliberately only the two steps whose own question text offers an
/// escape hatch — `region` says "you can skip this, say 'anywhere'" and
/// `restrictions` says "(or 'none')". The chip is just that offer made
/// tappable.
///
/// `collecting_purpose` gets none on purpose. graph.py's comment on
/// FIELD_QUESTIONS records that the question was rewritten to be open
/// specifically because listing categories primed people to answer in the
/// vocabulary that throws away the most information — 49% of the corpus's
/// itineraries hook on interests a fixed category list cannot express
/// (K-drama locations, halal food, pet-friendly, backpacking). Category
/// chips here would reintroduce exactly that priming through the UI.
///
/// `collecting_dates` gets none because no canned date is a useful answer,
/// and `confirm` needs none — the "Build My Itinerary" CTA already is one.
List<String> _quickRepliesFor(String step) {
  switch (step) {
    case 'collecting_region':
      return const ['Anywhere'];
    case 'collecting_restrictions':
      return const ['None'];
    default:
      return const [];
  }
}
