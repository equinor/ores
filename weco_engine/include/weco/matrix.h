/*

Association Scientifique pour la Geologie et ses Applications (ASGA)

Copyright (c) 2018 ASGA. All Rights Reserved.

This program is a Trade Secret of the ASGA and it is not to be:
 * reproduced, published, or disclosed to other,
 * distributed or displayed,
 * used for purposes or on Sites other than described in the GOCAD Advancement Agreement,
   without the prior written authorization of the ASGA.

Licencee agrees to attach or embed this Notice on all copies of the program,
including partial copies or modified versions thereof.

*/

#ifndef __weco_matrix_h__
#define __weco_matrix_h__

#include <vector>
#include <assert.h>

namespace WeCo {



/// Simple matrix
template <class T>
class Matrix {
public :
	Matrix():
		xsize_(0),ysize_(0)
		{};
	Matrix(unsigned xsize,unsigned ysize):
		xsize_(xsize),ysize_(ysize),data_(xsize_*ysize_)
		{assert (xsize>0 &&xsize >0);};
	Matrix(unsigned xsize,unsigned ysize,const T&value):
		xsize_(xsize),ysize_(ysize),data_(xsize_*ysize_,value)
		{assert (xsize>0 &&xsize >0);};
	~Matrix(){};

	const T& operator() (unsigned x,unsigned y) const {
		assert (x <xsize_ && y <ysize_);
		return data_[y*xsize_+x];
	};
	T& operator() (unsigned x,unsigned y)  {
		assert (x <xsize_ && y <ysize_);
		return data_[y*xsize_+x];
	};

	unsigned xsize()const {return xsize_;}
	unsigned ysize()const {return ysize_;}

	void resize(unsigned xsize,unsigned ysize) {
		assert(xsize>0 && ysize>0);
		xsize_ =xsize;
		ysize_ =ysize;
		data_.resize(xsize*ysize);
	}
	void fill(const T&value) {
		std::fill(data_.begin(),data_.end(),value);
	}


private:
	unsigned xsize_;
	unsigned ysize_;
	std::vector<T> data_;
};



}

#endif
