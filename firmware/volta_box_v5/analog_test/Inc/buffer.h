/*
 * buffer.h
 *
 *  Created on: Oct 23, 2017
 *      Author: direvius
 */

#ifndef BUFFER_H_
#define BUFFER_H_

#include <stdint.h>

#define RINGBUF_SIZE 32

struct ringbuf_t {
	uint16_t buf_[RINGBUF_SIZE];
	uint16_t *wp_;
	uint16_t *rp_;
	uint16_t *tail_;
	uint16_t remain_;
};


void rb_init(struct ringbuf_t *rb);

void rb_push(struct ringbuf_t *rb, uint16_t value);

uint16_t rb_pop(struct ringbuf_t *rb);

uint16_t rb_remain(const struct ringbuf_t *rb);

#endif /* BUFFER_H_ */
