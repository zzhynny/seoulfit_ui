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
      quickReplies: _quickRepliesFor(state.currentField),
      awaitingField: state.currentField,
      awaitingStep: state.currentStep,
    );
  }
}

/// One-tap answers for the slot the buddy is waiting on.
///
/// Keyed on `current_field`, not `current_step`. The backend's step stays
/// `"collecting"` for the whole intake — it is `current_field` that names the
/// one question being asked, because the buddy asks strictly one field per
/// turn (FIELD_ORDER in graph.py).
///
/// The options mirror what each question already offers in its own text, so
/// a chip is that offer made tappable rather than a second vocabulary the
/// planner has to interpret.
///
/// `travel_dates` gets none deliberately: its question says "Tap the calendar
/// to pick your dates", and graph.py notes the wording omits "or how many
/// days?" precisely because a typed duration is what the picker-only rule
/// rejects. Chips here would invite exactly the answer the backend refuses —
/// that slot needs a date picker, which this screen does not yet have.
List<String> _quickRepliesFor(String? field) {
  switch (field) {
    case 'category':
      // The five interest labels, verbatim. They must match graph.py's
      // FIELD_EXTRACT["category"] and each course's `interests` field exactly —
      // the match is a string compare, not a similarity score, so a chip that
      // reads "Culture" instead of "Culture & History" silently stops matching.
      return const [
        'Culture & History',
        'Food & Cafes',
        'Shopping',
        'K-POP & Hallyu',
        'Nature & Relaxation',
      ];
    case 'companion':
      return const ['Solo', 'Couple', 'Friends', 'Family'];
    case 'pace':
      return const ['Packed', 'Relaxed'];
    case 'restrictions':
      return const ['None'];
    case 'purpose':
      // Free text is the point — a chip would collapse it back into a label.
      // Only the skip is offered.
      return const ['Skip'];
    default:
      return const [];
  }
}
