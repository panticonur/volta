/*
 * buffer.c
 *
 *  Created on: Oct 23, 2017
 *      Author: direvius
 */

#include "buffer.h"

void rb_init(struct ringbuf_t *rb) {
	rb->wp_ = rb->buf_;
	rb->rp_ = rb->buf_;
	rb->tail_ = rb->buf_ + RINGBUF_SIZE;
	rb->remain_ = 0;
}

void rb_push(struct ringbuf_t *rb, uint16_t value) {
	if (rb->remain_ == RINGBUF_SIZE) rb_pop(rb);
	*(rb->wp_++) = value;
	rb->remain_++;
	if (rb->wp_ == rb->tail_)
		rb->wp_ = rb->buf_;
}

uint16_t rb_pop(struct ringbuf_t *rb) {
	uint16_t result = *(rb->rp_++);
	rb->remain_--;
	if (rb->rp_ == rb->tail_)
		rb->rp_ = rb->buf_;
	return result;
}

uint16_t rb_remain(const struct ringbuf_t *rb) {
	return rb->remain_;
}
