import 'package:flutter/material.dart';
import '../../theme/theme.dart';

enum LensPhotoSource { camera, gallery }

class LensScanScreen extends StatefulWidget {
  const LensScanScreen({super.key, required this.onScan});

  final ValueChanged<LensPhotoSource> onScan;

  @override
  State<LensScanScreen> createState() => _LensScanScreenState();
}

class _LensScanScreenState extends State<LensScanScreen> {
  bool _scanning = false;

  void _selectSource(LensPhotoSource source) {
    if (_scanning) return;
    setState(() => _scanning = true);
    widget.onScan(source);
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        Image.asset('assets/images/lens-scan-bg.png', fit: BoxFit.cover),
        Container(color: Colors.black.withValues(alpha: 0.35)),
        Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 8, 24, 0),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(30)),
                    child: Text('📷 Seoul Lens', style: AppTextStyles.caption.copyWith(color: Colors.white, fontWeight: FontWeight.w700)),
                  ),
                  const SizedBox(width: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.1),
                      border: Border.all(color: Colors.white.withValues(alpha: 0.2)),
                      borderRadius: BorderRadius.circular(30),
                    ),
                    child: Text('Seoul Open Data', style: AppTextStyles.caption.copyWith(color: Colors.white.withValues(alpha: 0.9), fontWeight: FontWeight.w600)),
                  ),
                ],
              ),
            ),
            const Spacer(),
            SizedBox(
              width: 220,
              height: 220,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  for (final alignment in [Alignment.topLeft, Alignment.topRight, Alignment.bottomLeft, Alignment.bottomRight])
                    Align(alignment: alignment, child: _cornerBracket(alignment)),
                  GestureDetector(
                    onTap: () => _selectSource(LensPhotoSource.camera),
                    child: Container(
                      width: 64,
                      height: 64,
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.15),
                        shape: BoxShape.circle,
                        border: Border.all(color: Colors.white.withValues(alpha: 0.8)),
                      ),
                      child: const Icon(Icons.camera, color: Colors.white, size: 28),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 32),
              child: Column(
                children: [
                  Text('Point at a Seoul landmark', style: AppTextStyles.headingSmall.copyWith(fontSize: 22, color: Colors.white)),
                  const SizedBox(height: 8),
                  Text(
                    'Take a photo or pick one from your gallery, and Seoul Lens will identify it with opening hours and more.',
                    textAlign: TextAlign.center,
                    style: AppTextStyles.bodySmall.copyWith(color: Colors.white.withValues(alpha: 0.8)),
                  ),
                ],
              ),
            ),
            const Spacer(),
            // 12-1_Lens-Scan's "bottom-sheet" — a persistent card docked
            // above the bottom nav (not a tap-triggered modal), visible by
            // default whenever this tab is open.
            _photoSourceSheet(),
          ],
        ),
        if (_scanning)
          Positioned.fill(
            child: Container(
              color: Colors.black.withValues(alpha: 0.55),
              child: const Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(color: Colors.white),
                    SizedBox(height: 16),
                    Text('Identifying landmark…', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _photoSourceSheet() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(24, 12, 24, 24),
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.only(topLeft: Radius.circular(24), topRight: Radius.circular(24)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: Container(
              width: 36,
              height: 4,
              margin: const EdgeInsets.only(bottom: 20),
              decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2)),
            ),
          ),
          Text('Seoul Lens', style: AppTextStyles.headingSmall.copyWith(fontSize: 24)),
          const SizedBox(height: 4),
          Text('Choose a photo source', style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary)),
          const SizedBox(height: 20),
          Row(
            children: [
              Expanded(child: _sourceButton('📷 Camera', LensPhotoSource.camera)),
              const SizedBox(width: 12),
              Expanded(child: _sourceButton('🖼️ Gallery', LensPhotoSource.gallery)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _sourceButton(String label, LensPhotoSource source) {
    return SizedBox(
      height: 48,
      child: ElevatedButton(
        onPressed: () => _selectSource(source),
        style: ElevatedButton.styleFrom(
          backgroundColor: const Color(0xFFE8EFEB),
          elevation: 0,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        ),
        child: Text(label, style: AppTextStyles.bodyMedium.copyWith(color: AppColors.primary, fontWeight: FontWeight.w700)),
      ),
    );
  }

  Widget _cornerBracket(Alignment alignment) {
    return SizedBox(
      width: 24,
      height: 24,
      child: CustomPaint(painter: _BracketPainter(alignment: alignment)),
    );
  }
}

class _BracketPainter extends CustomPainter {
  _BracketPainter({required this.alignment});
  final Alignment alignment;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke;
    final path = Path();
    if (alignment == Alignment.topLeft) {
      path.moveTo(0, size.height);
      path.lineTo(0, 0);
      path.lineTo(size.width, 0);
    } else if (alignment == Alignment.topRight) {
      path.moveTo(0, 0);
      path.lineTo(size.width, 0);
      path.lineTo(size.width, size.height);
    } else if (alignment == Alignment.bottomLeft) {
      path.moveTo(0, 0);
      path.lineTo(0, size.height);
      path.lineTo(size.width, size.height);
    } else {
      path.moveTo(size.width, 0);
      path.lineTo(size.width, size.height);
      path.lineTo(0, size.height);
    }
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
