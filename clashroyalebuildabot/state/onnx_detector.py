import numpy as np
import onnxruntime
from PIL import ImageOps


class OnnxDetector:
    def __init__(self, model_path):
        self.model_path = model_path
        self.sess = onnxruntime.InferenceSession(
            self.model_path,
            providers=["CPUExecutionProvider", "CUDAExecutionProvider"],
        )
        self.output_name = self.sess.get_outputs()[0].name

        input_ = self.sess.get_inputs()[0]
        self.input_name = input_.name
        self.model_height, self.model_width = input_.shape[2:]

    @staticmethod
    def _xywh_to_xyxy(boxes):
        boxes[:, 0] -= boxes[:, 2] / 2
        boxes[:, 1] -= boxes[:, 3] / 2
        boxes[:, 2] += boxes[:, 0]
        boxes[:, 3] += boxes[:, 1]

    @staticmethod
    def _nms(boxes, scores, thresh):
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        areas = (x2 - x1 + 1) * (y2 - y1 + 1)
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0.0, xx2 - xx1 + 1)
            h = np.maximum(0.0, yy2 - yy1 + 1)
            inter = w * h
            ovr = inter / (areas[i] + areas[order[1:]] - inter)
            inds = np.where(ovr <= thresh)[0]
            order = order[inds + 1]
        return keep

    def resize(self, x):
        min_size = min(self.model_width, self.model_height)
        x = ImageOps.contain(x, (min_size, min_size))
        return x

    def pad(self, x):
        height, width = x.shape[:2]
        dx = self.model_width - width
        dy = self.model_height - height
        pad_right = dx // 2
        pad_left = dx - pad_right
        pad_bottom = dy // 2
        pad_top = dy - pad_bottom
        padding = [pad_left, pad_right, pad_top, pad_bottom]
        x = np.pad(
            x,
            ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0)),
            mode="constant",
            constant_values=114,
        )
        return x, padding

    def fix_bboxes(self, x, width, height, padding):
        x[:, [0, 2]] -= padding[0]
        x[:, [1, 3]] -= padding[2]
        x[..., [0, 2]] *= width / (self.model_width - padding[0] - padding[1])
        x[..., [1, 3]] *= height / (
            self.model_height - padding[2] - padding[3]
        )
        return x

    def nms(self, prediction, conf_thres=0.35, iou_thres=0.45):
        output = [np.zeros((0, 6))] * len(prediction)
        for i in range(len(prediction)):
            x = prediction[i]
            scores = x[:, 4:]
            best_scores_idx = np.argmax(scores, axis=1).reshape(-1, 1)
            best_scores = np.take_along_axis(scores, best_scores_idx, axis=1)
            mask = np.ravel(best_scores > conf_thres)
            best_scores = best_scores[mask]
            best_scores_idx = best_scores_idx[mask]
            boxes = x[mask, :4]
            self._xywh_to_xyxy(boxes)
            keep = self._nms(boxes, np.ravel(best_scores), iou_thres)
            best = np.hstack(
                [boxes[keep], best_scores[keep], best_scores_idx[keep]]
            )
            output[i] = best
        return output

    def _infer(self, x):
        return self.sess.run([self.output_name], {self.input_name: x})[0]

    def _post_process(self, pred):
        raise NotImplementedError

    def run(self, image):
        raise NotImplementedError
